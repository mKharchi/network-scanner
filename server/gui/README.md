# Tauri + React + Typescript

This template should help get you started developing with Tauri, React and Typescript in Vite.

## Recommended IDE Setup

- [VS Code](https://code.visualstudio.com/) + [Tauri](https://marketplace.visualstudio.com/items?itemName=tauri-apps.tauri-vscode) + [rust-analyzer](https://marketplace.visualstudio.com/items?itemName=rust-lang.rust-analyzer)

## Linux Launcher

Use [`launch_gui.sh`](/home/adonis/network-scanner/server/gui/launch_gui.sh) to start the Tauri app from the `server/gui` folder.

For the packaged app, use [`launch_gui_release.sh`](/home/adonis/network-scanner/server/gui/launch_gui_release.sh). It launches the built binary from `src-tauri/target/release/netwatch-gui`.

If you want a desktop shortcut, copy [`netwatch-gui.desktop`](/home/adonis/network-scanner/server/gui/netwatch-gui.desktop) to your desktop or to `~/.local/share/applications/`, then make sure `launch_gui.sh` is executable:

```bash
chmod +x /home/adonis/network-scanner/server/gui/launch_gui.sh
chmod +x /home/adonis/network-scanner/server/gui/launch_gui_release.sh
chmod +x /home/adonis/network-scanner/server/gui/netwatch-gui.desktop
```

If the file manager still refuses to launch it, right-click the shortcut and choose `Allow Launching` or the equivalent trust option in your desktop environment.
