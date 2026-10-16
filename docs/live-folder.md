# Live Folder

**Live Folder** (the button in the Workbench's top bar, or File > Live Folder) watches the folder your camera software saves into. Each photo that lands in it is read in and shown as it arrives, so you can shoot a roll from the computer and see every frame as you take it.

## What it is for

Canon's **EOS Utility** (and the other tethering programs) can fire the camera from the computer and save every shot into a folder on it, over a USB cable or over Wi-Fi. Live Folder takes it from there: it does not talk to the camera, it watches that folder. So it works with any program that puts photos into a folder, and with photos you copy in by hand.

## Using it

1. In the camera's software, set where the photos are saved to the computer (in EOS Utility, its preferences have a Destination Folder; choose to save to the computer, or the computer and the card). Make a folder for the roll if you like.
2. In the editor, open the **Workbench** and press **Live Folder**. The first time it asks which folder to watch: pick the one the camera software saves into. It is remembered; **...** next to the button has **Choose Folder...** to change it.
3. Shoot. A photo shows about two seconds after its file is complete (a large RAW file that is still coming over Wi-Fi is waited for, so it is never opened half-written).
4. Press **Live Folder** again (or File > Live Folder) to stop. It always starts off when the editor opens.

Camera software that makes a sub-folder for each day (EOS Utility does by default) is fine: sub-folders of the watched folder are watched too.

## What happens to each photo

- It is read into the library (so it has its place in the Workbench with its camera, lens, ISO and so on).
- In the Workbench it is **selected and scrolled into view**, so its details are on the right at once. If the Workbench's search or filters are hiding it, the status line says so.
- **Show Each New Photo in the Editor** (in the **...** menu, on by default) opens it in the editor too, so you see it large with the negative converted: check focus, exposure and the edges before you shoot the next frame. Turn it off to stay in the Workbench and only have the new photo selected. The editor's filmstrip lists the new frame as it arrives.

Photos already in the folder when you turn it on are not "new": they are read into the Workbench and left alone.

## If nothing shows

- The folder must be the one the camera software really saves into. Shoot one frame and look for the file in that folder in Explorer.
- Only photo files are watched (JPEG, TIFF, PNG and the RAW formats the editor opens, which include Canon's CR2 and CR3). A name that ends in `.tmp` is the camera software's work file and is ignored until it is renamed.
- Over Wi-Fi a RAW file can take a while to arrive. The Live Folder waits until the file stops growing. A USB cable is faster and steadier for a whole roll; Wi-Fi is fine for a few test frames.
- Canon's own notes on the connection: [Connecting to EOS Utility](https://cam.start.canon/en/C011/manual/html/UG-08_Network_0050.html).
