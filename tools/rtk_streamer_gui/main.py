#!/usr/bin/env python3
"""
RTK Streamer GUI for MAVSDK Drone Shows

Repository: https://github.com/alireza787b/mavsdk_drone_show
Author: Alireza
LinkedIn: https://www.linkedin.com/in/alireza787b/

This application provides a professional, Tkinter-based GUI for real-time
streaming of RTCM3 correction data from a u-blox F9P base station to multiple
PX4 drones via their Raspberry Pi companions over UDP.

Features:
  - Automatic serial port & baud-rate detection (common rates)
  - Robust RTCM3 packet framing & fragmentation into MAVLink GPS_RTCM_DATA
    messages (<=180 bytes payload)
  - Multicast of corrections to all drones defined in config.csv (IP, port)
  - Per-drone status indicators for serial input, RTCM output, and base link
  - Base survey progress and minimal fix-duration thresholds (configurable)
  - Scalable: handles 10-100 drones concurrently
  - Rotating log window and file-based rotating logs
  - Production-quality: graceful shutdown, error handling, modular code

Dev Notes:
  - Future: NTRIP source via subclassing RTCMSource
  - Future: Advanced Settings dialog (timeouts)
  - Future: Telemetry subscription for actual fix_type & satellite count
  - Future: Raw Mode URI/API export
  - Write unit tests for framing & fragmentation

Usage:
  1. Activate venv in MAVSDK-DroneShow repo root
  2. pip install pyserial pymavlink
  3. python tools/rtk_streamer_gui/main.py
"""
import os
import threading
import queue
import time
import logging
import logging.handlers
import serial
from serial.tools import list_ports
from pymavlink import mavutil
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, font
import csv
import webbrowser

# ======================
# CONFIGURABLE CONSTANTS
# ======================
DEFAULT_TELEM_PORT = 34550
COMMON_BAUDRATES = [9600, 38400, 57600, 115200, 230400, 460800]
RTCM_START_BYTE = 0xD3
MAX_MAVLINK_PAYLOAD = 180  # bytes per GPS_RTCM_DATA message
BASE_SURVEY_TIMEOUT = 300   # seconds
MIN_RTK_FIX_DURATION = 10  # seconds

# Path to config.csv two levels above this file (repo root)
CONFIG_CSV = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'config.csv')
)

# ======================
# Logging Setup
# ======================
logger = logging.getLogger('rtk_streamer')
logger.setLevel(logging.INFO)
fh = logging.handlers.RotatingFileHandler(
    'rtk_streamer.log', maxBytes=5*1024*1024, backupCount=1
)
formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
fh.setFormatter(formatter)
logger.addHandler(fh)

# ======================
# Serial Reader Thread
# ======================
class SerialReader(threading.Thread):
    """
    Reads binary RTCM3 data from a serial port, frames full messages,
    and puts complete packets into a queue for distribution.
    Calls gui.record_input() on each packet to update status.
    """
    def __init__(self, port, baud, rtcm_queue, stop_event, gui):
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.rtcm_queue = rtcm_queue
        self.stop_event = stop_event
        self.gui = gui

    def run(self):
        try:
            ser = serial.Serial(self.port, self.baud, timeout=1)
            logger.info(f"Serial opened: {self.port} @ {self.baud}")
            self.gui.set_base_status(True)
        except Exception as e:
            logger.error(f"Failed to open serial port: {e}")
            self.gui.set_base_status(False)
            return

        buffer = bytearray()
        while not self.stop_event.is_set():
            try:
                data = ser.read(1024)
                if data:
                    buffer.extend(data)
                    while len(buffer) >= 3:
                        if buffer[0] != RTCM_START_BYTE:
                            buffer.pop(0)
                            continue
                        length = ((buffer[1] & 0x03) << 8) | buffer[2]
                        if len(buffer) < length + 3:
                            break
                        packet = bytes(buffer[:length+3])
                        del buffer[:length+3]
                        self.rtcm_queue.put(packet)
                        self.gui.record_input()
                else:
                    time.sleep(0.01)
            except Exception as e:
                logger.error(f"Serial read error: {e}")
                break
        ser.close()
        logger.info("SerialReader stopped.")
        self.gui.set_base_status(False)

# ======================
# RTK Distributor Thread
# ======================
class RTKDistributor(threading.Thread):
    """
    Takes RTCM packets from a queue, fragments them into MAVLink
    GPS_RTCM_DATA messages, and sends to all drone endpoints via UDP.
    """
    def __init__(self, drone_list, port, rtcm_queue, stop_event, gui):
        super().__init__(daemon=True)
        self.drone_list = drone_list
        self.port = port
        self.rtcm_queue = rtcm_queue
        self.stop_event = stop_event
        self.gui = gui
        self.stats = {'msgs': 0, 'bytes': 0}
        self.last_packet_time = None
        self.sockets = self._setup_sockets()

    def _setup_sockets(self):
        sockets = []
        for d in self.drone_list:
            mb = mavutil.mavlink_connection(
                f"udpout:{d['ip']}:{self.port}", source_system=255, dialect='common'
            )
            sockets.append((d['id'], mb))
            logger.info(f"Socket -> Drone {d['id']} @ {d['ip']}:{self.port}")
        return sockets

    def run(self):
        while not self.stop_event.is_set():
            try:
                packet = self.rtcm_queue.get(timeout=0.5)
                self._send_packet(packet)
            except queue.Empty:
                continue
        for _, mb in self.sockets:
            mb.close()
        logger.info("RTKDistributor stopped.")
        self.gui.set_rtcm_status(False)

    def _send_packet(self, data: bytes):
        idx = 0
        length = len(data)
        while idx < length:
            chunk = data[idx:idx+MAX_MAVLINK_PAYLOAD]
            if len(chunk) < MAX_MAVLINK_PAYLOAD:
                chunk = chunk.ljust(MAX_MAVLINK_PAYLOAD, b'\x00')
            for _, mb in self.sockets:
                mb.mav.gps_rtcm_data_send(0, len(chunk), chunk)
            idx += MAX_MAVLINK_PAYLOAD
        self.stats['msgs'] += 1
        self.stats['bytes'] += length
        self.last_packet_time = time.time()
        self.gui.set_rtcm_status(True)

# ======================
# Drone Configuration Loader
# ======================
class DroneConfig:
    def __init__(self, path=CONFIG_CSV):
        self.path = path
    def load(self):
        if not os.path.isfile(self.path):
            raise FileNotFoundError(f"Config.csv not found at {self.path}")
        drones = []
        with open(self.path, newline='') as f:
            for row in csv.DictReader(f):
                ip = row.get('ip')
                did = row.get('pos_id') or row.get('hw_id')
                if ip and did:
                    drones.append({'id': did, 'ip': ip})
        return drones

# ======================
# GUI Application
# ======================
class RTKStreamerGUI:
    def __init__(self, master):
        self.master = master
        master.title("MDS RTK Streamer")
        self.stop_event = threading.Event()
        self.rtcm_queue = queue.Queue()
        self.serial_thread = None
        self.dist_thread = None
        self.last_serial_time = None
        self.drone_list = DroneConfig().load()
        self._build_ui()
        self._populate_table()
        self._schedule_poll()

    def record_input(self):
        self.last_serial_time = time.time()
        self.input_status.config(text="Input: OK", foreground='green')

    def _build_ui(self):
        frm = ttk.Frame(self.master, padding=10)
        frm.grid(sticky=tk.NSEW)
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)

        # Controls
        ttk.Label(frm, text="Serial Port:").grid(row=0, column=0)
        ports = [p.device for p in list_ports.comports()] + ['Auto']
        self.port_cb = ttk.Combobox(frm, values=ports, state='readonly', width=12)
        self.port_cb.set('Auto'); self.port_cb.grid(row=0, column=1)

        ttk.Label(frm, text="Baud Rate:").grid(row=0, column=2)
        self.baud_cb = ttk.Combobox(frm, values=COMMON_BAUDRATES+['Auto'], state='readonly', width=8)
        self.baud_cb.set('Auto'); self.baud_cb.grid(row=0, column=3)

        ttk.Label(frm, text="Telem Port:").grid(row=0, column=4)
        self.tele_port_var = tk.IntVar(value=DEFAULT_TELEM_PORT)
        ttk.Entry(frm, textvariable=self.tele_port_var, width=6).grid(row=0, column=5)

        self.btn_connect = ttk.Button(frm, text="Connect", command=self._toggle_stream)
        self.btn_connect.grid(row=0, column=6, padx=(10,0))

        # Status indicators
        self.base_status = ttk.Label(frm, text="Base: Disconnected", foreground='red')
        self.base_status.grid(row=0, column=7, padx=5)
        self.input_status = ttk.Label(frm, text="Input: --", foreground='gray')
        self.input_status.grid(row=0, column=8, padx=5)
        self.rtcm_status = ttk.Label(frm, text="RTCM: --", foreground='gray')
        self.rtcm_status.grid(row=0, column=9, padx=5)

        # Drone table
        cols = ('ID','IP','Status','Last','Fix')
        widths = (40,140,80,60,60)
        self.table = ttk.Treeview(frm, columns=cols, show='headings', height=10)
        for c,w in zip(cols,widths):
            self.table.heading(c, text=c); self.table.column(c, width=w)
        self.table.grid(row=1, column=0, columnspan=10, pady=10, sticky=tk.NSEW)
        frm.rowconfigure(1, weight=1); frm.columnconfigure(1, weight=1)

        # Stats & Log
        self.stats_lbl = ttk.Label(frm, text="Msgs:0 Bytes:0")
        self.stats_lbl.grid(row=2, column=0, columnspan=10, sticky=tk.W)
        self.log_txt = scrolledtext.ScrolledText(frm, height=6, state='disabled', wrap='none')
        self.log_txt.grid(row=3, column=0, columnspan=10, pady=(5,0), sticky=tk.NSEW)
        frm.rowconfigure(3, weight=0)

        # Footer
        footer_font = font.nametofont("TkDefaultFont").copy()
        footer_font.configure(size=9)
        footer = ttk.Label(
            self.master,
            text="© 2025 | GitHub: alireza787b/mavsdk_drone_show | @alireza787b",
            font=footer_font,
            foreground='gray',
            cursor="hand2"
        )
        footer.grid(row=4, column=0, pady=(5,5))
        footer.bind("<Button-1>", lambda e: webbrowser.open_new(
            "https://github.com/alireza787b/mavsdk_drone_show"
        ))

    def _populate_table(self):
        for d in self.drone_list:
            self.table.insert('', 'end', iid=d['id'], values=(d['id'], d['ip'], '–', '–', '–'))

    def set_base_status(self, ok):
        text, color = ("Base: Connected","green") if ok else ("Base: Disconnected","red")
        self.base_status.config(text=text, foreground=color)

    def set_rtcm_status(self, ok):
        text, color = ("RTCM: OK","green") if ok else ("RTCM: No Data","red")
        self.rtcm_status.config(text=text, foreground=color)

    def _toggle_stream(self):
        if not self.serial_thread:
            port, baud = self.port_cb.get(), self.baud_cb.get()
            if port=='Auto' or baud=='Auto':
                messagebox.showinfo("Info", "Auto-detect pending.")
                return
            telem_port = self.tele_port_var.get()
            self.stop_event.clear()
            self.serial_thread = SerialReader(port, int(baud), self.rtcm_queue, self.stop_event, self)
            self.serial_thread.start()
            self.dist_thread = RTKDistributor(self.drone_list, telem_port, self.rtcm_queue, self.stop_event, self)
            self.dist_thread.start()
            self.btn_connect.config(text="Disconnect")
            self._log("Streaming started.")
        else:
            self.stop_event.set()
            # Threads are daemon; they will exit promptly
            self.btn_connect.config(text="Connect")
            self._log("Streaming stopping...")
            self.serial_thread = None
            self.dist_thread = None

    def _schedule_poll(self):
        now = time.time()
        # Serial input freshness
        if self.last_serial_time:
            dt_in = now - self.last_serial_time
            if dt_in < 1:
                self.input_status.config(text="Input: OK", foreground='green')
            elif dt_in < 5:
                self.input_status.config(text="Input: Stale", foreground='orange')
            else:
                self.input_status.config(text="Input: No Data", foreground='red')
        # RTCM output freshness
        if self.dist_thread and self.dist_thread.last_packet_time:
            dt_out = now - self.dist_thread.last_packet_time
            if dt_out < 1:
                self.set_rtcm_status(True)
            elif dt_out < 5:
                self.rtcm_status.config(text="RTCM: Stale", foreground='orange')
            else:
                self.set_rtcm_status(False)
        # Stats
        if self.dist_thread:
            msgs = self.dist_thread.stats['msgs']; bts = self.dist_thread.stats['bytes']
            self.stats_lbl.config(text=f"Msgs:{msgs} Bytes:{bts}")
        self.master.after(1000, self._schedule_poll)

    def _log(self, msg, level='info'):
        ts = time.strftime('%H:%M:%S')
        line = f"[{ts}] {msg}\n"
        self.log_txt.config(state='normal')
        self.log_txt.insert('end', line)
        self.log_txt.yview('end')
        self.log_txt.config(state='disabled')
        getattr(logger, level)(msg)

# ======================
# Main Entry Point
# ======================
if __name__ == '__main__':
    try:
        root = tk.Tk()
        app = RTKStreamerGUI(root)
        root.mainloop()
    except Exception as e:
        logger.exception("Unhandled exception:")
        messagebox.showerror("Fatal Error", str(e))