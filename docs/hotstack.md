# Hotstack

A **hotstack** is a folder you mark as the one your photos land in. It is watched: each photo that arrives in it is shown as it arrives, so you can shoot a roll from the computer and see every frame as you take it.

## What it is for

Canon's **EOS Utility** (and the other tethering programs) can fire the camera from the computer and save every shot into a folder on it, over a USB cable or over Wi-Fi. A hotstack takes it from there: EFAS does not talk to the camera, it watches that folder. So it works with any program that puts photos into a folder, and with photos you copy in by hand.

## Marking a folder

1. In the camera's software, set where the photos are saved to the computer (in EOS Utility, its preferences have a Destination Folder; choose to save to the computer, or the computer and the card).
2. In EFAS, find that folder in a **Library** list (the Workbench's left column, or the editor's). If it is not there, add it with the **+** button.
3. **Right-click the folder and choose Mark as Hotstack.** Its icon and name turn red, in both Library lists, and the choice is saved. To undo it, right-click it again: **Remove Hotstack Mark**.

That is all: a marked folder is watched from then on, every time the editor is open. Any folder can be marked, not only a top-level one, and more than one can be. If a marked folder is inside another marked folder the outer one is watched, and it covers the inner one. Taking a folder off the Library list unmarks it.

## What happens to each photo

A photo shows about two seconds after its file is complete (a large RAW file that is still coming over Wi-Fi is waited for, so it is never opened half-written). Camera software that makes a sub-folder for each day (EOS Utility does by default) is fine: the folders inside a hotstack are watched too.

- It is read into the library, so it has its place in the Workbench with its camera, lens, ISO and so on.
- In the Workbench it is **selected and scrolled into view**, so its details are on the right at once. If the Workbench's search or filters are hiding it, the status line says so.
- **Show Each New Photo in the Editor** (in the menu of the flame button in the Workbench's top bar, on by default) opens it in the editor too, so you see it large with the negative converted: check focus, exposure and the edges before you shoot the next frame. Turn it off to stay in the Workbench and only have the new photo selected. The editor's filmstrip lists the new frame as it arrives.

Photos that were already in the folder when it was marked (or when the editor was opened) are not "new": they are read into the Workbench and left alone.

## Retaking a photo

If a frame came out wrong, shoot it again and let the new photo take its place:

1. Select the photo in the Workbench and press **Retake This Photo** (or right-click it and choose Retake, or File > Retake Open Photo, or right-click its tile in the editor's filmstrip). The status line says the retake is armed. Press the button again (it now says **Cancel Retake**) or choose File > Cancel Retake to change your mind. A retake needs a hotstack folder to catch the new photo.
2. Shoot the frame again. The next photo to arrive **takes the old photo's name and place**: if the old one was `4N0A7869.CR2` in the day's folder, the retake is now `4N0A7869.CR2` there, in the same spot in the roll.
3. The old photo is **set aside, not deleted**: it goes into a `Retakes` folder beside where it was, with its sidecars, and is taken off the Workbench (bring it back from **Removed Photos**). Its edits, rating, flag and tags stay with it. A second retake of the same name goes in next to the first as `_1`.

The retake **starts from the old photo's edits** (crop, negative settings, film base, tags and notes), so a roll that is set up does not have to be set up again; its rating and flag are cleared, because they judged the old photo. If the retake needs different settings (a change of exposure, a different crop), use Reset in the editor. If the old photo is open in the editor, the editor shows the new file straight away.

A retake only takes one photo: if several arrive at once, the first one replaces the old photo and the rest are ordinary arrivals. If the photo to retake has been moved or deleted before the new one arrives, the new photo is kept as an ordinary arrival and the status line says so.

## Finishing a session

Every photo that arrives in a hotstack is part of the **session**, until you finish it. When you are done shooting, go to the hotstack folder - browse it in the Workbench's Library list, or select one of its photos, or open one of them in the editor - and press **Finish Session (n)** in the Workbench's top bar (also File > Finish Session...). The button is only there while you are in a hotstack folder and there are photos to file.

1. It lists how many photos it will move and into which folder, and asks you to confirm.
2. Each photo is **moved into a folder named for the day** of its file, `DD-MM-YYYY` (the same name the Export panel's date sub-folders use), inside the hotstack folder it is in. A day that ran past midnight makes two folders. The retaken photos that were set aside go into a `Retakes` folder inside that day's folder. Nothing is deleted, and a photo is never written over another: a name that is taken becomes `_1`, `_2`.
3. Everything saved for a photo goes with it: its edits and their history, versions, rating, flag, tags, notes and film base, and its sidecar files. The folder's own **flat field and Roll Card are given to the dated folder** too (unless it has its own), so the roll keeps looking the way you set it up. The hotstack stays marked and watched, and the filed photos are not reported as new.

The session is kept when you close the editor, so you can finish it the next day. Only the photos that arrived while the folder was a hotstack are moved: the others in the folder are left alone, and so is a photo you retook that was not part of the session (it is replaced where it is).

## If nothing shows

- The folder must be the one the camera software really saves into. Shoot one frame and look for the file in that folder in Explorer.
- Only photo files are watched (JPEG, TIFF, PNG and the RAW formats the editor opens, which include Canon's CR2 and CR3). A name that ends in `.tmp` is the camera software's work file and is ignored until it is renamed.
- Over Wi-Fi a RAW file can take a while to arrive. The hotstack waits until the file stops growing. A USB cable is faster and steadier for a whole roll; Wi-Fi is fine for a few test frames.
- The flame button's menu says which folders are being watched. A marked folder on a drive that is not connected is watched as soon as the drive is back.
- Canon's own notes on the connection: [Connecting to EOS Utility](https://cam.start.canon/en/C011/manual/html/UG-08_Network_0050.html).
