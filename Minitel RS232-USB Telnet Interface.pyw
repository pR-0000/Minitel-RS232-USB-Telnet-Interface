#!/usr/bin/env python3
# Minitel RS232/USB Telnet Interface

import sys, subprocess, time, threading, traceback
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

version = "0.2.1"

# --- Dependencies -------------------------------------------------------------
try:
    import serial
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyserial"])
    import serial
import serial.tools.list_ports

try:
    from twisted.internet import reactor, protocol
    from twisted.internet.error import ConnectionDone
    from twisted.protocols.basic import LineReceiver
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "twisted"])
    from twisted.internet import reactor, protocol
    from twisted.internet.error import ConnectionDone
    from twisted.protocols.basic import LineReceiver

# --- Globals -----------------------------------------------------------------
connection_active = False
ser = None

# Recording
recording_active = False
record_buffer = bytearray()

# --- Videotex init sequences --------------------------------------------------
def build_init_sequence():
    """
    Init stream WITHOUT G1 selection:
     - disable local echo
     - hide cursor
     - clear screen
     - clear line 0 (twice)
     - HOME cursor (0,0) with 0x1E
    """
    return (
        b'\x1B\x3B\x60\x58\x52'  # disable local echo
        b'\x14'                  # hide cursor
        b'\x0C'                  # clear screen
        b'\x1F\x40\x41'          # US row=0 col=1
        b'\x18\x18'              # EL x2 (clear line 0)
        b'\x1E'                  # RS -> home cursor to 0,0
    )

def build_disable_echo_sequence():
    """Only disable local echo (pre-connection if requested)."""
    return b'\x1B\x3B\x60\x58\x52'

# --- Model detection & max speed ---------------------------------------------
def detect_and_configure_minitel(port_name, set_speed_on_terminal=True):
    """
    Probe 7E1 at 1200/4800/9600 to read 'ESC 9 {' response.
    Optionally set target speed on terminal via ESC : k (does not change framing).
    PC framing is NEVER changed here (we keep 7E1).
    """
    import time
    types = {
        0x62: ("Minitel 1", 1200),
        0x63: ("Minitel 1", 1200),
        0x64: ("Minitel 10", 1200),
        0x65: ("Minitel 1 Couleur", 1200),
        0x66: ("Minitel 10", 1200),
        0x67: ("Emulator", 9600),
        0x72: ("Minitel 1", 1200),
        0x73: ("Minitel 1 Couleur", 1200),
        0x74: ("Terminatel 252", 1200),
        0x75: ("Minitel 1 Bi-standard", 4800),
        0x76: ("Minitel 2", 9600),
        0x77: ("Minitel 10 Bi-standard", 4800),
        0x78: ("Thomson ?", 1200),
        0x79: ("Minitel 5", 1200),
        0x7A: ("Minitel 12", 1200),
    }
    # PROBE 7E1 ONLY (including 9600)
    probe = [
        (1200, serial.SEVENBITS, serial.PARITY_EVEN),
        (4800, serial.SEVENBITS, serial.PARITY_EVEN),
        (9600, serial.SEVENBITS, serial.PARITY_EVEN),
    ]
    for baud, bits, parity in probe:
        try:
            s = serial.Serial(
                port=port_name, baudrate=baud, bytesize=bits, parity=parity,
                stopbits=serial.STOPBITS_ONE, timeout=1
            )
            s.reset_input_buffer()
            s.write(b'\x1B\x39\x7B')  # ESC 9 {
            time.sleep(0.4)
            resp = s.read(5)
            s.close()
            if len(resp) >= 5 and resp[0] == 0x01 and resp[4] == 0x04:
                type_code = resp[2]
                model_info, target_speed = types.get(type_code, ("Unknown", 1200))
                if set_speed_on_terminal and target_speed != baud:
                    try:
                        s2 = serial.Serial(
                            port=port_name, baudrate=baud, bytesize=bits, parity=parity,
                            stopbits=serial.STOPBITS_ONE, timeout=1
                        )
                        speed_bits = {4800: 0b110, 9600: 0b111}.get(target_speed, 0b100)  # 1200=100
                        config_byte = (1 << 6) | (speed_bits << 3) | speed_bits  # P=0,1,E,R
                        s2.write(b'\x1B\x3A\x6B' + bytes([config_byte]))  # ESC : k -> set speed
                        time.sleep(0.2)
                        s2.close()
                    except Exception:
                        pass
                return model_info, target_speed
        except Exception:
            pass
    return "Unknown", 1200

# --- GUI ---------------------------------------------------------------------
def open_gui():
    window = tk.Tk()
    window.title("Minitel RS232/USB Telnet Interface")
    window.geometry("640x820")
    window.minsize(620, 780)

    # Variables
    com_port_var = tk.StringVar()
    baudrate_var = tk.IntVar()
    data_bits_var = tk.IntVar()
    parity_var = tk.StringVar()
    stop_bits_var = tk.IntVar(value=1)
    server_address_var = tk.StringVar(value="go.minipavi.fr")
    server_port_var = tk.IntVar(value=516)
    show_messages_var = tk.BooleanVar(value=True)
    encoding_var = tk.StringVar(value="hexadecimal")

    auto_connect_var = tk.BooleanVar(value=True)      # auto-detect model & max speed
    disable_echo_preconnect_var = tk.BooleanVar(value=True)  # send echo-off before connect
    poll_interval_var = tk.DoubleVar(value=0.06)      # serial poll interval (s)

    # Recording options
    record_bidir_var = tk.BooleanVar(value=False)
    record_wrap_stxetx_var = tk.BooleanVar(value=False)
    record_prepend_init_var = tk.BooleanVar(value=True)   # default ON for better playback

    send_prepend_init_var = tk.BooleanVar(value=False)    # optional when sending a .vdt file

    # Helpers ------------------------------------------------------------------
    def log_message(message, is_communication=False):
        if is_communication and not show_messages_var.get():
            return
        timestamp = datetime.now().strftime("[%H:%M:%S] ")
        console_text.config(state='normal')
        console_text.insert(tk.END, timestamp + message + "\n")
        console_text.config(state='disabled')
        console_text.see(tk.END)

    def clear_console():
        console_text.config(state='normal'); console_text.delete('1.0', tk.END); console_text.config(state='disabled')

    def list_serial_ports():
        ports = serial.tools.list_ports.comports()
        return [f"{port.device} - {port.description}" for port in ports]

    def refresh_ports():
        com_port_menu['values'] = list_serial_ports()
        log_message("Ports refreshed.")

    def decode_data(data):
        enc = encoding_var.get()
        if enc == "hexadecimal":
            return " ".join(f"{b:02X}" for b in data)
        else:
            try:
                return data.decode(enc, errors='replace')
            except Exception:
                return str(data)

    def toggle_manual_fields():
        state = 'disabled' if auto_connect_var.get() else 'readonly'
        baudrate_menu.configure(state=state)
        data_bits_menu.configure(state=state)
        parity_menu.configure(state=state)
        stop_bits_menu.configure(state=state)

    # Serial helpers -----------------------------------------------------------
    def close_serial_connection():
        global ser
        if ser and ser.is_open:
            try:
                ser.close()
                log_message("Serial connection closed.")
            except Exception as e:
                log_message(f"Error closing serial: {e}")
        ser = None

    def read_from_minitel(factory):
        global ser, recording_active, record_buffer
        if factory.client and ser and ser.is_open:
            try:
                data_from_minitel = ser.read(512)
            except Exception:
                data_from_minitel = b''
            if data_from_minitel:
                decoded = decode_data(data_from_minitel)
                log_message(f"From Minitel → Server: {decoded}", is_communication=True)
                factory.client.sendData(data_from_minitel)
                if recording_active and record_bidir_var.get():
                    record_buffer.extend(data_from_minitel)
        if reactor.running:
            reactor.callLater(max(0.01, poll_interval_var.get()), read_from_minitel, factory)

    # Twisted protocol ---------------------------------------------------------
    class MinitelTelnetClient(LineReceiver):
        def connectionMade(self):
            log_message("Connected to server.")
            set_connection_state(True)

        def dataReceived(self, data):
            global ser, recording_active, record_buffer
            if ser and ser.is_open:
                try:
                    ser.write(data)
                except Exception as e:
                    log_message(f"Serial write error: {e}")
            decoded = decode_data(data)
            log_message(f"From Server → Minitel: {decoded}", is_communication=True)
            if recording_active:
                record_buffer.extend(data)

        def lineReceived(self, line):
            self.dataReceived(line + b'\n')

        def sendData(self, data):
            if not isinstance(data, bytes):
                raise TypeError("Data must be bytes")
            self.transport.write(data)
            log_message(f"Sent to server: {decode_data(data)}", is_communication=True)

    class MinitelClientFactory(protocol.ClientFactory):
        def __init__(self):
            self.client = None

        def buildProtocol(self, addr):
            self.client = MinitelTelnetClient()
            return self.client

        def clientConnectionFailed(self, connector, reason):
            log_message(f"Failed to connect to server: {reason}")
            close_serial_connection()
            set_connection_state(False)

        def clientConnectionLost(self, connector, reason):
            if reason.check(ConnectionDone):
                log_message("Connection to server closed cleanly.")
            else:
                log_message(f"Lost connection to server: {reason}")
            close_serial_connection()
            set_connection_state(False)

    # Start/Stop ---------------------------------------------------------------
    def start_connection():
        global ser
        if connection_active:
            stop_connection()
            return

        selected = com_port_var.get()
        com_port = selected.split(" - ")[0] if selected else ""
        if not com_port:
            log_message("Error: No COM port selected.")
            return

        # Auto-detect (does NOT change PC framing)
        if auto_connect_var.get():
            model, target_speed = detect_and_configure_minitel(
                com_port,
                set_speed_on_terminal=True
            )
            baudrate_var.set(target_speed)
            # Force 7E1 on PC side regardless of target speed
            data_bits_var.set(7)
            parity_var.set("Even")
            stop_bits_var.set(1)
            log_message(f"Auto-detect: {model} — speed set to {target_speed} bps; framing kept at 7E1.")

        baudrate = baudrate_var.get()
        data_bits = data_bits_var.get()
        parity = parity_var.get().lower()
        stop_bits = stop_bits_var.get()
        server_address = server_address_var.get()
        server_port = server_port_var.get()

        log_message(f"Opening serial {com_port} @ {baudrate} bps, {data_bits} bits, parity {parity}, {stop_bits} stop.")
        try:
            ser_local = serial.Serial(
                port=com_port,
                baudrate=baudrate,
                bytesize=serial.SEVENBITS if data_bits == 7 else serial.EIGHTBITS,
                parity=serial.PARITY_EVEN if parity == "even" else serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE if stop_bits == 1 else serial.STOPBITS_TWO,
                timeout=1
            )
            ser_local.reset_input_buffer()
            ser_local.reset_output_buffer()
        except serial.SerialException as e:
            log_message(f"Serial open error: {e}")
            return

        # assign global after success
        globals()['ser'] = ser_local
        log_message("Serial connection established.")

        # Disable local echo before connecting (if requested)
        if disable_echo_preconnect_var.get():
            try:
                ser.write(build_disable_echo_sequence())
                log_message("Sent: disable local echo (pre-connect).")
            except Exception as e:
                log_message(f"Error sending echo-off: {e}")

        # Start Twisted reactor (single thread)
        if not reactor.running:
            threading.Thread(target=reactor.run, kwargs={"installSignalHandlers": False}, daemon=True).start()

        # Connect to server & start polling
        try:
            factory = MinitelClientFactory()
            reactor.callFromThread(reactor.connectTCP, server_address, int(server_port), factory)
            reactor.callLater(poll_interval_var.get(), read_from_minitel, factory)
        except Exception as e:
            log_message(f"Error starting networking: {e}")
            close_serial_connection()
            return

    def stop_connection():
        log_message("Stopping connection...")
        close_serial_connection()
        set_connection_state(False)

    def set_connection_state(connected):
        global connection_active
        connection_active = connected
        start_button.config(text="Stop connection" if connected else "Start connection")

    # Recording controls --------------------------------------------------------
    def toggle_recording():
        global recording_active, record_buffer
        if not recording_active:
            record_buffer = bytearray()
            recording_active = True
            record_button.config(text="Stop & Save .vdt")
            log_message(f"Recording started ({'bidirectional' if record_bidir_var.get() else 'server→Minitel'}).")
        else:
            recording_active = False
            record_button.config(text="Start recording")
            vdt = bytes(record_buffer)
            if record_prepend_init_var.get():
                vdt = build_init_sequence() + vdt
            if record_wrap_stxetx_var.get():
                vdt = b'\x02' + vdt + b'\x03'
            path = filedialog.asksaveasfilename(
                title="Save capture as .vdt",
                defaultextension=".vdt",
                filetypes=[("Videotex .vdt", "*.vdt"), ("All files", "*.*")]
            )
            if path:
                try:
                    with open(path, "wb") as f:
                        f.write(vdt)
                    log_message(f"Saved capture: {path} ({len(vdt)} bytes)")
                except Exception as e:
                    log_message(f"Error saving .vdt: {e}")
            else:
                log_message("Save cancelled; capture discarded.")

    # Sending a .vdt file ------------------------------------------------------
    def strip_stx_etx(data: bytes):
        if len(data) >= 2 and data[0] == 0x02 and data[-1] == 0x03:
            return data[1:-1], True
        return data, False

    def send_vdt_file():
        global ser
        path = filedialog.askopenfilename(
            title="Select a .vdt file to send",
            filetypes=[("Videotex .vdt", "*.vdt"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
        except Exception as e:
            log_message(f"Error reading .vdt: {e}")
            return

        data, had_frame = strip_stx_etx(data)
        if had_frame:
            log_message("Detected STX/ETX in file — stripped before sending.")
        if send_prepend_init_var.get():
            data = build_init_sequence() + data

        # Ensure serial is open; if not, open with current settings
        temp_opened = False
        if not ser or not ser.is_open:
            selected = com_port_var.get()
            com_port = selected.split(" - ")[0] if selected else ""
            if not com_port:
                log_message("Error: No COM port selected for sending.")
                return
            try:
                ser_local = serial.Serial(
                    port=com_port,
                    baudrate=baudrate_var.get(),
                    bytesize=serial.SEVENBITS if data_bits_var.get() == 7 else serial.EIGHTBITS,
                    parity=serial.PARITY_EVEN if parity_var.get().lower() == "even" else serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE if stop_bits_var.get() == 1 else serial.STOPBITS_TWO,
                    timeout=1
                )
                ser_local.reset_input_buffer()
                ser_local.reset_output_buffer()
                ser = ser_local
                temp_opened = True
                log_message("Serial opened temporarily for .vdt send.")
            except Exception as e:
                log_message(f"Serial open error: {e}")
                return

        try:
            t0 = time.time()
            CHUNK = 1024
            total = 0
            for i in range(0, len(data), CHUNK):
                chunk = data[i:i+CHUNK]
                ser.write(chunk)
                total += len(chunk)
            ser.flush()
            dt = time.time() - t0
            log_message(f"Sent .vdt ({total} bytes) in {dt:.2f}s.")
        except Exception as e:
            log_message(f"Error sending .vdt: {e}")
        finally:
            if temp_opened:
                try:
                    ser.close()
                    ser = None
                    log_message("Temporary serial connection closed.")
                except Exception:
                    pass

    # --- Layout ---------------------------------------------------------------
    r = 0
    tk.Label(window, text="COM Port:").grid(row=r, column=0, sticky="w", padx=8, pady=4)
    com_port_menu = ttk.Combobox(window, textvariable=com_port_var, values=list_serial_ports(), state='readonly')
    com_port_menu.grid(row=r, column=1, sticky="ew", padx=8, pady=4)
    tk.Button(window, text="Refresh", command=refresh_ports).grid(row=r, column=2, sticky="ew", padx=8, pady=4)

    r += 1
    tk.Label(window, text="Baud Rate:").grid(row=r, column=0, sticky="w", padx=8, pady=4)
    baudrate_menu = ttk.Combobox(window, textvariable=baudrate_var, values=[300,1200,4800,9600], state='readonly')
    baudrate_menu.grid(row=r, column=1, sticky="ew", padx=8, pady=4)

    r += 1
    tk.Label(window, text="Data Bits:").grid(row=r, column=0, sticky="w", padx=8, pady=4)
    data_bits_menu = ttk.Combobox(window, textvariable=data_bits_var, values=[7, 8], state='readonly')
    data_bits_menu.grid(row=r, column=1, sticky="ew", padx=8, pady=4)

    r += 1
    tk.Label(window, text="Parity:").grid(row=r, column=0, sticky="w", padx=8, pady=4)
    parity_menu = ttk.Combobox(window, textvariable=parity_var, values=["None", "Even"], state='readonly')
    parity_menu.grid(row=r, column=1, sticky="ew", padx=8, pady=4)

    r += 1
    tk.Label(window, text="Stop Bits:").grid(row=r, column=0, sticky="w", padx=8, pady=4)
    stop_bits_menu = ttk.Combobox(window, textvariable=stop_bits_var, values=[1, 2], state='readonly')
    stop_bits_menu.grid(row=r, column=1, sticky="ew", padx=8, pady=4)

    r += 1
    auto_cb = tk.Checkbutton(window, text="Auto-connection at maximum speed", variable=auto_connect_var, command=toggle_manual_fields)
    auto_cb.grid(row=r, column=0, columnspan=3, sticky="w", padx=8, pady=4)

    r += 1
    echo_cb = tk.Checkbutton(window, text="Disable local echo before connecting", variable=disable_echo_preconnect_var)
    echo_cb.grid(row=r, column=0, columnspan=3, sticky="w", padx=8, pady=2)

    r += 1
    ttk.Separator(window, orient="horizontal").grid(row=r, column=0, columnspan=3, sticky="ew", padx=8, pady=6)

    r += 1
    tk.Label(window, text="Server Address:").grid(row=r, column=0, sticky="w", padx=8, pady=4)
    server_address_entry = tk.Entry(window, textvariable=server_address_var)
    server_address_entry.grid(row=r, column=1, columnspan=2, sticky="ew", padx=8, pady=4)

    r += 1
    tk.Label(window, text="Server Port:").grid(row=r, column=0, sticky="w", padx=8, pady=4)
    server_port_entry = tk.Entry(window, textvariable=server_port_var)
    server_port_entry.grid(row=r, column=1, columnspan=2, sticky="ew", padx=8, pady=4)

    r += 1
    tk.Label(window, text="Encoding:").grid(row=r, column=0, sticky="w", padx=8, pady=4)
    encoding_menu = ttk.Combobox(window, textvariable=encoding_var,
                                 values=["hexadecimal", "iso-8859-1", "cp850", "cp437", "iso-8859-15"],
                                 state='readonly')
    encoding_menu.grid(row=r, column=1, sticky="ew", padx=8, pady=4)

    r += 1
    tk.Label(window, text="Poll interval (s):").grid(row=r, column=0, sticky="w", padx=8, pady=4)
    poll_entry = tk.Entry(window, textvariable=poll_interval_var)
    poll_entry.grid(row=r, column=1, sticky="ew", padx=8, pady=4)

    r += 1
    show_messages_checkbox = tk.Checkbutton(window, text="Show serial/TCP traffic in console", variable=show_messages_var)
    show_messages_checkbox.grid(row=r, column=0, columnspan=3, sticky="w", padx=8, pady=4)

    r += 1
    btns = tk.Frame(window)
    btns.grid(row=r, column=0, columnspan=3, sticky="ew", padx=8, pady=8)
    start_button = tk.Button(btns, text="Start connection", command=start_connection)
    start_button.pack(side="left", expand=True, fill="x", padx=4)
    clear_btn = tk.Button(btns, text="Clear log", command=clear_console)
    clear_btn.pack(side="left", padx=4)
    send_vdt_btn = tk.Button(btns, text="Send .vdt file", command=send_vdt_file)
    send_vdt_btn.pack(side="left", padx=4)

    r += 1
    rec_frame = ttk.LabelFrame(window, text="Recording (.vdt)")
    rec_frame.grid(row=r, column=0, columnspan=3, sticky="ew", padx=8, pady=6)
    record_button = tk.Button(rec_frame, text="Start recording", command=lambda: toggle_recording())
    record_button.grid(row=0, column=0, sticky="w", padx=6, pady=4)
    tk.Checkbutton(rec_frame, text="Bidirectional (include Minitel→Server)", variable=record_bidir_var).grid(row=0, column=1, sticky="w", padx=6, pady=4)
    tk.Checkbutton(rec_frame, text="Wrap with STX/ETX", variable=record_wrap_stxetx_var).grid(row=1, column=0, sticky="w", padx=6, pady=2)
    tk.Checkbutton(rec_frame, text="Prepend init (echo off, cursor off, CLS, clear line 0, HOME)", variable=record_prepend_init_var).grid(row=1, column=1, sticky="w", padx=6, pady=2)
    tk.Checkbutton(rec_frame, text="Prepend init when sending .vdt", variable=send_prepend_init_var).grid(row=1, column=2, sticky="w", padx=6, pady=2)

    r += 1
    console_frame = tk.Frame(window)
    console_frame.grid(row=r, column=0, columnspan=3, sticky="nsew", padx=8, pady=8)
    console_text = tk.Text(console_frame, height=14, state='disabled', wrap='word')
    console_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    console_scrollbar = tk.Scrollbar(console_frame, command=console_text.yview)
    console_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    console_text['yscrollcommand'] = console_scrollbar.set

    window.columnconfigure(0, weight=1)
    window.columnconfigure(1, weight=1)
    window.columnconfigure(2, weight=0)
    window.rowconfigure(r, weight=1)  # console expands

    # Defaults (7E1)
    baudrate_var.set(1200)
    data_bits_var.set(7)
    parity_var.set("Even")
    stop_bits_var.set(1)
    toggle_manual_fields()

    log_message(f"Minitel RS232/USB Telnet Interface v{version}")
    log_message("---")
    log_message("Modes on terminal:")
    log_message("Fnct+T,V = Teletel CEPT 25×40 | Fnct+T,A = ISO 6429 ASCII 25×80 | Fnct+T,F = ISO 6429 French 25×80")
    log_message("In Telematic mode: Fnct+T,E (echo rule), Ctrl+J LF, Ctrl+H BS, Ctrl+I HT, Ctrl+K VT, Ctrl+← Del, Ctrl+X EL, Enter CR")
    log_message("---")

    window.mainloop()

if __name__ == "__main__":
    open_gui()
