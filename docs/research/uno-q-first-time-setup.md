# UNO Q first-time setup and SSH from Windows

- **Date:** 2026-10-23
- **Sources:** primary only. All paths below are relative to https://github.com/arduino/docs-content/blob/main/content/, the Markdown that docs.arduino.cc renders.

## Steps

1. **Connect with a plain USB-C data cable straight from the laptop to the Board. No hub yet.** [`software/app-lab/1.setup/2.windows/windows.md`]
   - The UNO Q has only one USB-C port. Once the hub is attached, the laptop loses its USB link to the Board, so do the first setup over the direct cable.
   - A charge-only cable won't work, because the Board has to show up as a USB device (inferred).
2. **Install Arduino App Lab on Windows and run the first-time setup wizard.** [`software/app-lab/2.configure/1.config/config.md`]
   - When it first launches, allow `mdns-discovery.exe` through the Windows firewall.
   - The wizard asks for:
     - a keyboard layout;
     - a **board name**, which becomes `<name>.local` on the network;
     - **Wi-Fi**: WPA/WPA2 Personal only, no captive portals [`.../3.network-configuration/network-configuration.md`];
     - a **Linux password** for the default user `arduino`.
   - It then offers updates. Install them.
   - Finishing the wizard turns SSH on automatically [`hardware/uno/boards/uno-q/tutorials/linux/ssh/ssh.md`].
3. **SSH in from Windows Terminal:** `ssh arduino@<name>.local` (OpenSSH is built into Windows). [`ssh.md`]
   - If `<name>.local` doesn't resolve, use the Board's IP address instead.
   - mDNS uses UDP port 5353 and SSH uses TCP port 22. [`network-configuration.md`]
   - To toggle SSH later, go to App Lab: Settings > System info > **Remote access (SSH)**. [`software/app-lab/2.configure/2.settings/settings.md`]
4. **Fallback with no network: `adb`.** Run `winget install Google.PlatformTools`, then `adb devices` and `adb shell` over the direct cable. [`hardware/uno/boards/uno-q/tutorials/linux/adb/adb.md`]
   - The password before setup is `arduino`.
   - `hostname -I` inside `adb shell` shows the Board's IP address.
5. **Switch to the hub for the Webcam phase.** Plug a ≥5 V / 3 A charger into the hub's PD port; the hub powers the Board. Avoid Apple multiport adapters. Keep working over SSH via Wi-Fi. [`hardware/uno/boards/uno-q/tutorials/guides/single-board-computer/content.md`]
6. **Copy files from the laptop** with `scp file arduino@<name>.local:/home/arduino/` and the reverse; use `scp -rp` for folders. [`ssh.md`]
   - `git clone` on the Board needs internet. Install git with `sudo apt install python3-pip git curl` if it isn't already there. [`hardware/uno/boards/uno-q/tutorials/linux/debian-guide/content.md`]

## Unverified

- SSH over Ethernet only, with no Wi-Fi configured.
- Whether git ships in the stock image.
