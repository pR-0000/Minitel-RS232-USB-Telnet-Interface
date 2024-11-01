# Minitel RS232/USB Telnet Interface

This application, **Minitel RS232/USB Telnet Interface**, allows users to connect a Minitel terminal via a USB/RS232 interface to Telnet servers. It facilitates bidirectional communication, making it possible to use your Minitel as a display terminal for BBS (Bulletin Board Systems), classic Telnet servers, and other compatible systems.

### Features
- Serial port configuration adapted to the Minitel (baud rate, parity, data bits, and stop bits).
- Real-time connection to Telnet servers, with options for ASCII encoding or hexadecimal display.
- A graphical interface (GUI) built in Python using `Tkinter` with a built-in console display.

### Requirements
- **Python 3.8+** (the application will install required libraries if they are not present).

### Usage
1. Connect your Minitel to your computer using a compatible RS232/USB adapter.
2. Run the application:
   ```bash
   python "Minitel RS232-USB Telnet Interface.pyw"
   ```
3. Configure the serial settings to match your Minitel model.
4. Enter the Telnet server address and port, and click **Start connection**.
5. Use the Minitel to interact with the connected server. The GUI console will display communication logs.

### Troubleshooting
- Ensure the correct COM port is selected and that no other applications are using it.
- For best results, consult your Minitel manual to verify compatibility and settings.

---

# Interface Telnet RS232/USB Minitel

Cette application, **Interface Telnet RS232/USB Minitel**, permet aux utilisateurs de connecter un terminal Minitel via une interface USB/RS232 à des serveurs Telnet. Elle facilite la communication bidirectionnelle, permettant d'utiliser votre Minitel comme terminal d'affichage pour les systèmes BBS (Bulletin Board Systems), les serveurs Telnet classiques, et d'autres systèmes compatibles.

### Fonctionnalités
- Configuration du port série adaptée au Minitel (vitesse en bauds, parité, bits de données et de stop).
- Connexion en temps réel à des serveurs Telnet, avec options pour l'affichage en ASCII ou en hexadécimal.
- Interface graphique (GUI) construite en Python avec `Tkinter` et une console intégrée.

### Prérequis
- **Python 3.8+** (l'application installera automatiquement les bibliothèques nécessaires si elles ne sont pas présentes).

### Utilisation
1. Connectez votre Minitel à votre ordinateur via un adaptateur RS232/USB compatible.
2. Lancez l'application :
   ```bash
   python "Minitel RS232-USB Telnet Interface.pyw"
   ```
3. Configurez les paramètres série pour correspondre au modèle de votre Minitel.
4. Entrez l'adresse et le port du serveur Telnet, puis cliquez sur **Start connection**.
5. Utilisez le Minitel pour interagir avec le serveur connecté. La console GUI affichera les journaux de communication.

### Dépannage
- Assurez-vous que le port COM correct est sélectionné et qu'aucune autre application ne l'utilise.
- Pour de meilleurs résultats, consultez le manuel de votre Minitel pour vérifier la compatibilité et les paramètres.
