#!/usr/bin/env python3
"""BlueGuard: authorized passive Bluetooth discovery and user-confirmed connections."""
import csv
import json
import os
import queue
import re
import select
import shutil
import subprocess
import threading
import time
import tkinter as tk
from datetime import datetime, timezone
from tkinter import filedialog, messagebox, ttk

APP_NAME = "BlueGuard Bluetooth Scanner"
VERSION = "1.1.0-1"
MAC_RE = re.compile(r"^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$")
FIELDS = ["address", "name", "device_hint", "transport", "rssi_dbm", "last_seen_utc"]

def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def guess_device_hint(name):
    """Best-effort label from the advertised name only; not OS fingerprinting."""
    value = (name or "").strip().lower()
    if not value:
        return "Other/Unknown"
    audio_tokens = ("airpods", "buds", "headphone", "headset", "speaker", "soundbar",
                    "jbl", "bose", "sony wh", "sony wf", "beats", "earbuds", "soundcore")
    if any(token in value for token in audio_tokens):
        return "Audio"
    android_tokens = ("android", "pixel", "galaxy", "redmi", "xiaomi", "oneplus",
                      "oppo", "vivo", "realme", "iqoo", "huawei", "honor", "motorola")
    if any(token in value for token in android_tokens):
        return "Android (likely)"
    mac_tokens = ("macbook", "imac", "mac mini", "mac studio", "mac pro")
    if any(token in value for token in mac_tokens):
        return "macOS (likely)"
    windows_tokens = ("windows", "surface", "xbox", "desktop-", "laptop-", "pc-")
    if any(token in value for token in windows_tokens):
        return "Windows (likely)"
    return "Other/Unknown"

class BlueGuard:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} v{VERSION}")
        self.root.geometry("1050x700")
        self.root.minsize(850, 580)
        self.events = queue.Queue()
        self.devices = {}
        self.proc = None
        self.reader = None
        self.stop_event = threading.Event()
        self.scanning = False
        self._style()
        self._ui()
        self.root.after(150, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.log("Ready. Use only with devices you own or are authorized to test.")
        if not shutil.which("bluetoothctl"):
            self.log("bluetoothctl missing. Install with: sudo apt install bluez")

    def _style(self):
        self.root.configure(bg="#10151f")
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=("DejaVu Sans", 10))
        style.configure("TFrame", background="#10151f")
        style.configure("Panel.TFrame", background="#182130")
        style.configure("TLabel", background="#10151f", foreground="#e8edf5")
        style.configure("Muted.TLabel", background="#182130", foreground="#aab7c8")
        style.configure("Treeview", background="#182130", foreground="#e8edf5", fieldbackground="#182130", rowheight=25)
        style.configure("Treeview.Heading", background="#263449", foreground="#ffffff")
        style.map("Treeview", background=[("selected", "#275d88")])

    def _ui(self):
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text="BLUEGUARD", font=("DejaVu Sans", 21, "bold")).pack(side="left")
        ttk.Label(header, text="Bluetooth discovery & authorized device tools").pack(side="left", padx=15, pady=(7,0))
        ttk.Label(outer, text="Passive discovery • Pair/connect actions require explicit confirmation").pack(anchor="w", pady=(4,10))

        controls = ttk.Frame(outer, style="Panel.TFrame", padding=10)
        controls.pack(fill="x", pady=(0,10))
        ttk.Label(controls, text="Mode", style="Muted.TLabel").grid(row=0,column=0,sticky="w")
        self.mode = tk.StringVar(value="Classic + BLE")
        self.mode_box = ttk.Combobox(controls,textvariable=self.mode,values=["Classic + BLE","Classic","BLE"],state="readonly",width=17)
        self.mode_box.grid(row=1,column=0,padx=(0,10))
        ttk.Label(controls,text="Duration (5–600 s)",style="Muted.TLabel").grid(row=0,column=1,sticky="w")
        self.duration = tk.StringVar(value="30")
        ttk.Entry(controls,textvariable=self.duration,width=8).grid(row=1,column=1,padx=(0,10))
        self.start_btn = ttk.Button(controls,text="Start scan",command=self.start_scan)
        self.start_btn.grid(row=1,column=2,padx=4)
        self.stop_btn = ttk.Button(controls,text="Stop",command=self.stop_scan,state="disabled")
        self.stop_btn.grid(row=1,column=3,padx=4)
        ttk.Button(controls,text="Export CSV",command=self.export_csv).grid(row=1,column=4,padx=4)
        ttk.Button(controls,text="Export JSON",command=self.export_json).grid(row=1,column=5,padx=4)

        filters = ttk.Frame(outer, style="Panel.TFrame", padding=10)
        filters.pack(fill="x", pady=(0,10))
        ttk.Label(filters, text="Filter by name", style="Muted.TLabel").grid(row=0,column=0,sticky="w")
        self.name_filter = tk.StringVar()
        ttk.Entry(filters, textvariable=self.name_filter, width=24).grid(row=1,column=0,padx=(0,10))
        ttk.Label(filters, text="Filter by MAC", style="Muted.TLabel").grid(row=0,column=1,sticky="w")
        self.mac_filter = tk.StringVar()
        ttk.Entry(filters, textvariable=self.mac_filter, width=22).grid(row=1,column=1,padx=(0,10))
        ttk.Label(filters, text="Likely device type", style="Muted.TLabel").grid(row=0,column=2,sticky="w")
        self.hint_filter = tk.StringVar(value="All")
        self.hint_box = ttk.Combobox(filters, textvariable=self.hint_filter,
            values=["All","Android (likely)","Windows (likely)","macOS (likely)","Audio","Other/Unknown"],
            state="readonly", width=19)
        self.hint_box.grid(row=1,column=2,padx=(0,10))
        ttk.Button(filters, text="Clear filters", command=self.clear_filters).grid(row=1,column=3,padx=4)
        self.name_filter.trace_add("write", self.apply_filters)
        self.mac_filter.trace_add("write", self.apply_filters)
        self.hint_filter.trace_add("write", self.apply_filters)

        connect = ttk.Frame(outer,style="Panel.TFrame",padding=10)
        connect.pack(fill="x",pady=(0,10))
        ttk.Label(connect,text="Device MAC address",style="Muted.TLabel").grid(row=0,column=0,sticky="w")
        self.mac = tk.StringVar()
        ttk.Entry(connect,textvariable=self.mac,width=22).grid(row=1,column=0,padx=(0,8))
        ttk.Button(connect,text="Use selected row",command=self.use_selected).grid(row=1,column=1,padx=4)
        ttk.Button(connect,text="Pair…",command=self.pair).grid(row=1,column=2,padx=4)
        ttk.Button(connect,text="Connect",command=self.connect).grid(row=1,column=3,padx=4)
        ttk.Button(connect,text="Disconnect",command=self.disconnect).grid(row=1,column=4,padx=4)
        ttk.Label(connect,text="Only use these actions on devices you own or have permission to manage.",style="Muted.TLabel").grid(row=2,column=0,columnspan=5,sticky="w",pady=(6,0))

        self.status = tk.StringVar(value="Idle")
        statusrow = ttk.Frame(outer)
        statusrow.pack(fill="x",pady=(0,6))
        ttk.Label(statusrow,textvariable=self.status).pack(side="left")
        self.count = tk.StringVar(value="0 devices")
        ttk.Label(statusrow,textvariable=self.count).pack(side="right")
        cols = ("address","name","device_hint","transport","rssi_dbm","last_seen_utc")
        self.tree = ttk.Treeview(outer,columns=cols,show="headings",selectmode="browse")
        titles = {"address":"MAC address","name":"Advertised name","device_hint":"Likely type (hint)","transport":"Mode","rssi_dbm":"RSSI dBm","last_seen_utc":"Last seen (UTC)"}
        widths = {"address":150,"name":210,"device_hint":135,"transport":105,"rssi_dbm":80,"last_seen_utc":180}
        for col in cols:
            self.tree.heading(col,text=titles[col]); self.tree.column(col,width=widths[col],anchor="w")
        self.tree.pack(fill="both",expand=True)
        self.tree.bind("<<TreeviewSelect>>",self.selected)
        logframe = ttk.Frame(outer,style="Panel.TFrame",padding=8)
        logframe.pack(fill="x",pady=(10,0))
        ttk.Label(logframe,text="Activity log",style="Muted.TLabel").pack(anchor="w")
        self.logbox = tk.Text(logframe,height=5,bg="#0c1119",fg="#c9d6e5",relief="flat",wrap="word")
        self.logbox.pack(fill="x",pady=(5,0)); self.logbox.configure(state="disabled")

    def log(self, text):
        self.logbox.configure(state="normal")
        self.logbox.insert("end",f"[{datetime.now().strftime('%H:%M:%S')}] {text}\n")
        self.logbox.see("end"); self.logbox.configure(state="disabled")

    def _send(self, command):
        proc = self.proc
        if proc and proc.poll() is None and proc.stdin:
            try:
                proc.stdin.write(command + "\n"); proc.stdin.flush()
            except (OSError, BrokenPipeError):
                pass

    def start_scan(self):
        if self.scanning:
            return
        try:
            duration = int(self.duration.get())
            if not 5 <= duration <= 600:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid duration","Choose a duration between 5 and 600 seconds."); return
        if not shutil.which("bluetoothctl"):
            messagebox.showerror("BlueZ missing","Install BlueZ: sudo apt install bluez"); return
        self.stop_event.clear()
        try:
            self.proc = subprocess.Popen(["bluetoothctl"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,env={**os.environ,"LANG":"C","LC_ALL":"C"})
        except OSError as exc:
            messagebox.showerror("Cannot start scan",str(exc)); return
        self.scanning = True
        self.start_btn.configure(state="disabled"); self.stop_btn.configure(state="normal"); self.mode_box.configure(state="disabled")
        self.status.set(f"Scanning {self.mode.get()}…")
        mode = self.mode.get()
        command = {"Classic":"scan bredr","BLE":"scan le","Classic + BLE":"scan on"}[mode]
        self._send("power on"); self._send(command)
        self.log(f"Started {mode} discovery for {duration}s.")
        self.reader = threading.Thread(target=self._read_output,args=(mode,duration),daemon=True)
        self.reader.start()

    def _read_output(self, mode, duration):
        start = time.monotonic()
        try:
            while not self.stop_event.is_set() and time.monotonic()-start < duration:
                if not self.proc or not self.proc.stdout:
                    break
                # select() keeps the scan timeout responsive even when no device
                # produces output; plain readline() can block indefinitely.
                ready, _, _ = select.select([self.proc.stdout], [], [], 0.2)
                if not ready:
                    if self.proc.poll() is not None:
                        break
                    continue
                line = self.proc.stdout.readline()
                if not line:
                    if self.proc.poll() is not None:
                        break
                    continue
                self._parse_line(line.strip(),mode)
        except Exception as exc:
            self.events.put(("log",f"Scanner output error: {exc}"))
        finally:
            self._send("scan off"); self._send("exit")
            if self.proc and self.proc.poll() is None:
                try: self.proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.proc.terminate()
            self.events.put(("finished",None))

    def _parse_line(self,line,mode):
        match = re.search(r"(?:\[(?:NEW|CHG|DEL)\]\s+)?Device\s+((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})(?:\s+(.*))?",line)
        if match:
            addr = match.group(1).upper(); tail = (match.group(2) or "").strip()
            if addr == "00:00:00:00:00:00": return
            name = tail if tail and not re.search(r"(RSSI|TxPower|UUID|ManufacturerData|ServiceData):",tail) else ""
            self.events.put(("device",(addr,name,mode)))
        rssi = re.search(r"RSSI:\s*(-?\d+)",line)
        addrmatch = re.search(r"((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})",line)
        if rssi and addrmatch:
            self.events.put(("rssi",(addrmatch.group(1).upper(),int(rssi.group(1)))))
        if any(x in line.lower() for x in ("failed","not available","not ready","permission denied","no default controller")):
            self.events.put(("log",line))

    def stop_scan(self):
        if self.scanning:
            self.stop_event.set(); self._send("scan off"); self._send("exit")
            self.status.set("Stopping scan…"); self.log("Stop requested.")

    def _poll(self):
        try:
            while True:
                kind,payload = self.events.get_nowait()
                if kind == "device":
                    addr,name,mode = payload
                    d = self.devices.setdefault(addr,{"address":addr,"name":"","device_hint":"Other/Unknown","transport":mode,"rssi_dbm":None,"last_seen_utc":now_utc()})
                    if name:
                        d["name"] = name
                        d["device_hint"] = guess_device_hint(name)
                    if d["transport"] != mode: d["transport"] = "Classic + BLE"
                    d["last_seen_utc"] = now_utc(); self._refresh(addr)
                    self.log(f"Discovered {addr} {name}".rstrip())
                elif kind == "rssi":
                    addr,value = payload
                    if addr in self.devices:
                        self.devices[addr]["rssi_dbm"] = value; self.devices[addr]["last_seen_utc"] = now_utc(); self._refresh(addr)
                elif kind == "log": self.log(payload)
                elif kind == "action":
                    action,addr,code,out = payload
                    self.log(f"{action} {addr} (exit {code}): {out}")
                    if code == 0: messagebox.showinfo(f"{action} result",out or f"{action} command returned successfully.")
                    else: messagebox.showwarning(f"{action} needs attention",out or "The command did not complete successfully.")
                elif kind == "finished":
                    self.scanning = False
                    self.start_btn.configure(state="normal"); self.stop_btn.configure(state="disabled"); self.mode_box.configure(state="readonly")
                    self.status.set(f"Idle • {len(self.devices)} device(s)")
                    self.log("Scan finished.")
        except queue.Empty:
            pass
        self.root.after(150,self._poll)

    def _matches_filters(self, d):
        name_q = self.name_filter.get().strip().casefold()
        mac_q = self.mac_filter.get().strip().casefold()
        hint_q = self.hint_filter.get()
        if name_q and name_q not in (d.get("name") or "").casefold():
            return False
        if mac_q and mac_q not in d["address"].casefold():
            return False
        if hint_q != "All" and d.get("device_hint", "Other/Unknown") != hint_q:
            return False
        return True

    def _refresh(self,addr):
        d = self.devices[addr]
        if not self._matches_filters(d):
            if self.tree.exists(addr):
                self.tree.delete(addr)
            self.count.set(f"{len(self.tree.get_children())} shown / {len(self.devices)} discovered")
            return
        vals = (addr,d["name"] or "(name not advertised)",d.get("device_hint","Other/Unknown"),d["transport"],"" if d["rssi_dbm"] is None else d["rssi_dbm"],d["last_seen_utc"])
        if self.tree.exists(addr): self.tree.item(addr,values=vals)
        else: self.tree.insert("", "end",iid=addr,values=vals)
        self.count.set(f"{len(self.tree.get_children())} shown / {len(self.devices)} discovered")

    def apply_filters(self, *_):
        for addr in list(self.devices):
            self._refresh(addr)

    def clear_filters(self):
        self.name_filter.set("")
        self.mac_filter.set("")
        self.hint_filter.set("All")

    def selected(self,_=None):
        sel = self.tree.selection()
        if sel:
            self.mac.set(sel[0]); self.log("Selected " + json.dumps(self.devices.get(sel[0],{})))

    def use_selected(self):
        sel = self.tree.selection()
        if not sel: messagebox.showinfo("Select device","Select a discovered device row first."); return
        self.mac.set(sel[0])

    def _address(self):
        addr = self.mac.get().strip().upper()
        if not MAC_RE.fullmatch(addr) or addr == "00:00:00:00:00:00":
            messagebox.showerror("Invalid address","Enter a MAC address like AA:BB:CC:DD:EE:FF."); return None
        return addr

    def _action(self, action):
        addr = self._address()
        if not addr: return
        prompts = {
            "pair":("Pair",f"Pair with {addr}? Only proceed if this is your device or you have explicit permission. Confirm any passkey or pairing prompt on your speaker."),
            "connect":("Connect",f"Request a normal Bluetooth connection to {addr}? This may work without a new pairing-code prompt only if the device/profile permits it or the device is already paired. BlueGuard cannot bypass authentication or force access to a protected device."),
            "disconnect":("Disconnect",f"Disconnect {addr}? Only manage a device you own or are authorized to control.")
        }
        title,body = prompts[action]
        if not messagebox.askyesno(f"Confirm {title.lower()}",body): return
        self.log(f"{title} requested for {addr}.")
        def worker():
            try:
                # Pair via bluetoothctl stdin to permit the normal agent to be enabled.
                if action == "pair":
                    args = ["bluetoothctl"]
                    proc = subprocess.run(args,input=f"agent on\ndefault-agent\npair {addr}\nexit\n",capture_output=True,text=True,timeout=45,env={**os.environ,"LANG":"C","LC_ALL":"C"})
                else:
                    proc = subprocess.run(["bluetoothctl",action,addr],capture_output=True,text=True,timeout=25,env={**os.environ,"LANG":"C","LC_ALL":"C"})
                out = ((proc.stdout or "") + (proc.stderr or "")).strip()
                self.events.put(("action",(title,addr,proc.returncode,out or "No output returned.")))
            except subprocess.TimeoutExpired:
                self.events.put(("action",(title,addr,124,"Timed out. Check range, pairing mode, passkey prompts, and device profile support.")))
            except Exception as exc:
                self.events.put(("action",(title,addr,1,str(exc))))
        threading.Thread(target=worker,daemon=True).start()

    def pair(self): self._action("pair")
    def connect(self): self._action("connect")
    def disconnect(self): self._action("disconnect")

    def _rows(self):
        return [self.devices[k] for k in sorted(self.devices)]

    def export_csv(self):
        if not self.devices: messagebox.showinfo("No results","Run a scan before exporting."); return
        path = filedialog.asksaveasfilename(defaultextension=".csv",filetypes=[("CSV","*.csv")],initialfile="blueguard-scan.csv")
        if not path: return
        try:
            with open(path,"w",newline="",encoding="utf-8") as f:
                w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerows(self._rows())
            self.log("Exported CSV: "+path)
        except OSError as exc: messagebox.showerror("Export failed",str(exc))

    def export_json(self):
        if not self.devices: messagebox.showinfo("No results","Run a scan before exporting."); return
        path = filedialog.asksaveasfilename(defaultextension=".json",filetypes=[("JSON","*.json")],initialfile="blueguard-scan.json")
        if not path: return
        try:
            with open(path,"w",encoding="utf-8") as f:
                json.dump({"application":APP_NAME,"version":VERSION,"exported_at_utc":now_utc(),"scope":"passive discovery; details depend on adapter and BlueZ","devices":self._rows()},f,indent=2)
            self.log("Exported JSON: "+path)
        except OSError as exc: messagebox.showerror("Export failed",str(exc))

    def close(self):
        if self.scanning: self.stop_scan()
        self.root.destroy()

def main():
    root=tk.Tk()
    BlueGuard(root)
    root.mainloop()

if __name__ == "__main__":
    main()
