## Minitel RS232/USB Telnet Interface
## Pierre Raimbault - 01/11/2024

version = 0.1

import subprocess, time, threading
import traceback
from datetime import datetime

try:
    import serial
except ImportError:
    subprocess.check_call(["python", "-m", "pip", "install", "pyserial"])
    import serial
import serial.tools.list_ports

try:
    from twisted.internet import reactor, protocol
    from twisted.internet.error import ConnectionDone
    from twisted.protocols.basic import LineReceiver
except ImportError:
    subprocess.check_call(["python", "-m", "pip", "install", "twisted"])
    from twisted.internet import reactor, protocol
    from twisted.internet.error import ConnectionDone
    from twisted.protocols.basic import LineReceiver

try:
    import tkinter as tk
except ImportError:
    subprocess.check_call(["python", "-m", "pip", "install", "tkinter"])
    import tkinter as tk
from tkinter import ttk, messagebox

DEFAULT_MINITEL_MODEL = "Minitel 1"
connection_active = False
ser = None

def open_gui():
    window = tk.Tk()
    window.title("Minitel RS232/USB Telnet Interface")
    window.geometry("400x600")

    model_var = tk.StringVar(value=DEFAULT_MINITEL_MODEL)
    com_port_var = tk.StringVar()
    baudrate_var = tk.IntVar()
    data_bits_var = tk.IntVar()
    parity_var = tk.StringVar()
    stop_bits_var = tk.IntVar(value=1)
    server_address_var = tk.StringVar(value="go.minipavi.fr")
    server_port_var = tk.IntVar(value=516)
    show_messages_var = tk.BooleanVar(value=True)
    encoding_var = tk.StringVar(value="hexadecimal")

    scrollbar = tk.Scrollbar(window)
    scrollbar.grid(row=8, column=2, sticky='ns')

    global console
    console = tk.Text(window, height=10, state='disabled', wrap='word', yscrollcommand=scrollbar.set)
    console.grid(row=8, column=0, columnspan=2, padx=5, pady=5, sticky='nsew')
    scrollbar.config(command=console.yview)

    def clear_console():
        console.config(state='normal')
        console.delete('1.0', tk.END)
        console.config(state='disabled')

    def log_message(message, is_communication=False):
        if is_communication and not show_messages_var.get():
            return
        timestamp = datetime.now().strftime("[%H:%M:%S] ")
        console.config(state='normal')
        console.insert(tk.END, timestamp + message + "\n")
        console.config(state='disabled')
        console.see(tk.END)

    def list_serial_ports():
        ports = serial.tools.list_ports.comports()
        return [f"{port.device} - {port.description}" for port in ports]

    def apply_model_settings(*args):
        clear_console()
        model = model_var.get()
        if model == "Minitel 1":
            baudrate_menu['values'] = [1200]
            baudrate_var.set(1200)
            data_bits_var.set(7)
            parity_var.set("Even")
        elif model == "Minitel 1B and later":
            baudrate_menu['values'] = [300, 1200, 4800]
            baudrate_var.set(4800)
            data_bits_var.set(7)
            parity_var.set("Even")
            log_message("To configure the serial port speed on your Minitel:")
            log_message("Fcnt + P, 3: 300 bits/s")
            log_message("Fcnt + P, 1: 1200 bits/s")
            log_message("Fcnt + P, 4: 4800 bits/s")
        elif model == "Minitel 2 or Magis Club":
            baudrate_menu['values'] = [300, 1200, 4800, 9600]
            baudrate_var.set(9600)
            data_bits_var.set(8 if baudrate_var.get() == 9600 else 7)
            parity_var.set("None" if baudrate_var.get() == 9600 else "Even")
            log_message("To configure the serial port speed on your Minitel:")
            log_message("Fcnt + P, 3: 300 bits/s")
            log_message("Fcnt + P, 1: 1200 bits/s")
            log_message("Fcnt + P, 4: 4800 bits/s")
            log_message("Fcnt + P, 9: 9600 bits/s")

    def decode_data(data):
        encoding = encoding_var.get()
        if encoding == "hexadecimal":
            return " ".join(f"{byte:02X}" for byte in data)
        else:
            try:
                return data.decode(encoding, errors='replace')
            except UnicodeDecodeError:
                return str(data)

    def close_serial_connection():
        global ser
        if ser and ser.is_open:
            ser.close()
            log_message("Serial connection closed.")
        ser = None

    def read_from_minitel(factory):
        global ser
        if factory.client and ser and ser.is_open:
            data_from_minitel = ser.read(256)
            if data_from_minitel:
                decoded_data = decode_data(data_from_minitel)
                log_message(f"Data received from Minitel: {decoded_data}", is_communication=True)
                factory.client.sendData(data_from_minitel)
        if reactor.running:
            reactor.callLater(0.1, read_from_minitel, factory)

    class MinitelTelnetClient(LineReceiver):
        def connectionMade(self):
            log_message("Connected to the server.")
            set_connection_state(True)

        def dataReceived(self, data):
            if ser and ser.is_open:
                decoded_data = decode_data(data)
                log_message(f"Data sent to Minitel: {decoded_data}", is_communication=True)
                ser.write(data)

        def lineReceived(self, line):
            self.dataReceived(line + b'\n')

        def sendData(self, data):
            if not isinstance(data, bytes):
                raise TypeError("Data must be bytes")
            self.transport.write(data)
            log_message(f"Data sent to server: {decode_data(data)}", is_communication=True)

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

    def start_connection():
        global connection_active, ser

        if connection_active:
            stop_connection()
            return

        selected_com = com_port_var.get()
        com_port = selected_com.split(" - ")[0]
        baudrate = baudrate_var.get()
        data_bits = data_bits_var.get()
        parity = parity_var.get().lower()
        stop_bits = stop_bits_var.get()
        server_address = server_address_var.get()
        server_port = server_port_var.get()

        if not com_port:
            log_message("Error: No COM port selected.")
            return

        log_message(f"Starting connection with {com_port}, baud rate {baudrate}, {data_bits} bits, parity {parity}, {stop_bits} stop bit(s), server {server_address}:{server_port}")

        def run_communication():
            global ser
            try:
                if ser is None or not ser.is_open:
                    ser = serial.Serial(
                        port=com_port,
                        baudrate=baudrate,
                        bytesize=serial.SEVENBITS if data_bits == 7 else serial.EIGHTBITS,
                        parity=serial.PARITY_EVEN if parity == "even" else serial.PARITY_NONE,
                        stopbits=serial.STOPBITS_ONE if stop_bits == 1 else serial.STOPBITS_TWO,
                        timeout=1
                    )
                    log_message("Serial connection established.")

                factory = MinitelClientFactory()
                reactor.connectTCP(server_address, server_port, factory)
                reactor.callLater(0.1, read_from_minitel, factory)

            except serial.SerialException as e:
                log_message(f"Serial connection error: {e}")
                log_message(traceback.format_exc())
                set_connection_state(False)
            except Exception as e:
                log_message("Unexpected error:")
                log_message(traceback.format_exc())
                set_connection_state(False)

        if not reactor.running:
            threading.Thread(target=reactor.run, kwargs={"installSignalHandlers": False}, daemon=True).start()
        run_communication()

    def stop_connection():
        log_message("Stopping connection...")
        close_serial_connection()
        set_connection_state(False)

    def set_connection_state(connected):
        global connection_active
        connection_active = connected
        start_button.config(text="Stop connection" if connected else "Start connection")

    tk.Label(window, text="Minitel Model:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
    model_menu = ttk.Combobox(window, textvariable=model_var, values=["Minitel 1", "Minitel 1B and later", "Minitel 2 or Magis Club"], state='readonly')
    model_menu.grid(row=0, column=1, sticky="ew", padx=5, pady=5)
    model_menu.bind("<<ComboboxSelected>>", apply_model_settings)

    tk.Label(window, text="COM Port:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
    com_ports = list_serial_ports()
    com_port_menu = ttk.Combobox(window, textvariable=com_port_var, values=com_ports, state='readonly')
    com_port_menu.grid(row=1, column=1, sticky="ew", padx=5, pady=5)

    tk.Label(window, text="Baud Rate:").grid(row=2, column=0, sticky="w", padx=5, pady=5)
    baudrate_menu = ttk.Combobox(window, textvariable=baudrate_var, state='readonly')
    baudrate_menu.grid(row=2, column=1, sticky="ew", padx=5, pady=5)

    tk.Label(window, text="Data Bits:").grid(row=3, column=0, sticky="w", padx=5, pady=5)
    data_bits_menu = ttk.Combobox(window, textvariable=data_bits_var, values=[7, 8], state='readonly')
    data_bits_menu.grid(row=3, column=1, sticky="ew", padx=5, pady=5)

    tk.Label(window, text="Parity:").grid(row=4, column=0, sticky="w", padx=5, pady=5)
    parity_menu = ttk.Combobox(window, textvariable=parity_var, values=["None", "Even"], state='readonly')
    parity_menu.grid(row=4, column=1, sticky="ew", padx=5, pady=5)

    tk.Label(window, text="Stop Bits:").grid(row=5, column=0, sticky="w", padx=5, pady=5)
    stop_bits_menu = ttk.Combobox(window, textvariable=stop_bits_var, values=[1], state='readonly')
    stop_bits_menu.grid(row=5, column=1, sticky="ew", padx=5, pady=5)

    tk.Label(window, text="Server Address:").grid(row=6, column=0, sticky="w", padx=5, pady=5)
    server_address_entry = tk.Entry(window, textvariable=server_address_var)
    server_address_entry.grid(row=6, column=1, sticky="ew", padx=5, pady=5)

    tk.Label(window, text="Server Port:").grid(row=7, column=0, sticky="w", padx=5, pady=5)
    server_port_entry = tk.Entry(window, textvariable=server_port_var)
    server_port_entry.grid(row=7, column=1, sticky="ew", padx=5, pady=5)

    show_messages_checkbox = tk.Checkbutton(window, text="Show Minitel Communication", variable=show_messages_var)
    show_messages_checkbox.grid(row=9, column=0, columnspan=2, sticky="w", padx=5, pady=5)

    tk.Label(window, text="Encoding:").grid(row=10, column=0, sticky="w", padx=5, pady=5)
    encoding_menu = ttk.Combobox(window, textvariable=encoding_var, values=["hexadecimal", "iso-8859-1", "cp850", "cp437", "iso-8859-15"], state='readonly')
    encoding_menu.grid(row=10, column=1, sticky="ew", padx=5, pady=5)

    start_button = tk.Button(window, text="Start connection", command=start_connection)
    start_button.grid(row=11, column=0, columnspan=2, sticky="ew", padx=5, pady=20)

    window.columnconfigure(0, weight=1)
    window.columnconfigure(1, weight=3)
    window.rowconfigure(8, weight=1)

    apply_model_settings()

    log_message(f"Minitel RS232/USB Telnet Interface v{version}")
    log_message("---")
    log_message("To switch modes on your Minitel :")
    log_message("Fnct + T, V = Teletel videotex CEPT profile 2 25×40")
    log_message("Fnct + T, A = Telematic ISO 6429 American ASCII 25×80 characters")
    log_message("Fnct + T, F = Telematic ISO 6429 French ASCII 25×80 characters")
    log_message("")
    log_message("In Telematic mode :")
    log_message("Fnct + T, E = reverse local echo rule")
    log_message("Ctrl + J = line feed")
    log_message("Ctrl + H = backspace")
    log_message("Ctrl + I = horizontal tabulation")
    log_message("Ctrl + K = vertical tabulation")
    log_message("Ctrl + ← = erase character")
    log_message("Ctrl + X = erase line")
    log_message("↲ = carriage return")
    log_message("")
    log_message("Please consult the Minitel user manual for more information.")
    log_message("---")

    window.mainloop()

open_gui()
