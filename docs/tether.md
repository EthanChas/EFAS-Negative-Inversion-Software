# Canon tethering and live view (Extra > Canon Tether and Live View)

EFAS can drive a Canon camera on a copy stand itself: it shows the camera's live picture (turned into a positive as you look, with focus peaking and a loupe), moves the lens from the
computer while a sharpness meter tells you when you have the sharpest spot, and takes the picture, saving it into a roll folder under a numbered name. It is for scanning film with a
camera: focus once, check it, then shoot the roll.

## Status: read this first

- **Canon only, and Windows only, so far.** Other makes would go behind the same interface (`features/tether/backend.py`) later. A Mac needs Canon's events collected a different way and
  its camera found from the main thread, which has not been done.
- **It has not yet met a real camera body.** The Canon side was written from Canon's documented SDK and checked against a stand-in for the SDK (tests/test_tether_edsdk.py: the order of calls,
  a live picture that is not ready yet, a busy camera, one release announcing a RAW and a JPEG, a file announced twice, a download that fails) and against a practice camera. A stand-in can
  prove EFAS makes sensible calls; it cannot prove Canon's real library agrees. The first real session may find something; please say what happened.
- **EFAS cannot include Canon's SDK.** Canon licenses EDSDK to each developer and it may not be passed on, so you get your own copy from Canon's developer site (it needs a free developer
  account, and Canon decides who gets one; a few regions limit it to businesses). EFAS only calls it.

The practice camera needs none of this: it is a made-up negative with a lens that goes out of focus as you drive it, and every control works on it.

## Getting ready

1. Get Canon's EDSDK for Windows, unpack it, and choose its folder in the window (the one holding the 64-bit `EDSDK.dll`; EFAS looks a few folders down, and prefers the 64-bit copy).
2. Connect the camera to the computer with a USB cable that carries data, straight into a port and not through a hub.
3. On the camera: switch **Wi-Fi and Bluetooth off** (a Canon body switches USB data off while wireless is on, and the only sign is that no camera is found), use a lens with its AF/MF switch
   on **AF** (the lens drive needs autofocus; with the lens on manual focus you focus by hand and everything else still works), and set the exposure on the camera: manual mode, a fixed
   shutter speed, aperture and ISO. EFAS does not change the camera's exposure settings. Shutter mode (electronic or mechanical) is a camera menu setting; EDSDK does not offer it.
4. Close EOS Utility, Lightroom or any phone app that has hold of the camera.
5. Choose **Canon camera** in the window and press **Connect**.

## The window

**Camera.** Practice camera or Canon camera, the folder of the SDK, and Connect. When connected it shows the camera's name and lens, and says why the lens cannot be driven if it cannot
(no lens, or the lens on manual focus).

**View.** *Show as a positive* uses EFAS's own Modern conversion (the same as in the editor), so you judge focus on what you will see; a plain flip would keep the orange mask and come out
cyan. The conversion is metered on the middle of the picture and re-made about twice a second. *Pick the Clear Film*, then click a patch of clear film between frames, and the conversion
knows the film's orange; *Forget* goes back to working it out. *Focus peaking* marks what is in focus in colour (blue sharp, green sharper, yellow very sharp, red the sharpest); the
*Peaking sensitivity* slider decides how much is marked (100% marks every sharp spot, 0% only the very sharpest). Holding **N** shows the other of positive and negative for as long as it is held
(the quick invert preview; **I** switches for good). The *loupe* enlarges the area under the mouse four times, from the camera's own pixels and not the smaller picture on screen. A red warning appears on the picture
when more than half a per cent of a colour is blown out: with film the clear border between frames should be bright but not blown out.

**Focus.** Nearer and Farther, each in coarse, medium and fine steps. One step of the lens can be smaller than the picture's own noise, so a press sends several; the counts (fine 1, medium
5, coarse 15) suit a macro lens on a copy stand and are a starting point for others. The keys are Left and Right (fine), with Shift for medium and Alt for coarse. The **sharpness meter** shows a
number that rises as focus improves, the best so far, and a short history, and a **grade** in words against the best so far (Sharpest within 3% of it, Sharp, Nearly there, Soft, Blurred): go past the sharpest spot and back, and the meter peaks there. It is relative: it depends on the subject, the
light and the size of the region, so it means something within one focusing session and nowhere else. It measures a square in the middle; click the picture to measure where you click,
*Centre* to go back, *Reset Best* to start the best-so-far over. **Corners** measures the middle and each corner and says if a corner is a lot softer: on a copy stand that means the camera is
not parallel to the film (or the lens is soft at its edge).

**Capture.** The roll folder, a name (the picture is saved as the name plus a frame number, `scan_0001`, with the camera's own extension, so a RAW and its JPEG share a number), the time to
wait before the shutter, and *Open each picture in EFAS*. **Capture** (Space) waits that long for the rig to stop shaking (vibration is the main cause of soft scans on a copy stand), presses
the shutter fully **without focusing** (focus stays where you put it, because it must not change between frames of a roll), and saves everything the camera makes into the folder. The next
number comes from what is already in the folder, so a roll can be picked up again later, and a file is never overwritten (a name that is taken gets `-1`). If one file of a shot cannot be
saved the others are kept and no half-written file is left.

## How it fits with the rest of EFAS

With *Open each picture in EFAS* on, each shot opens in the editor (the RAW when there is one) and its folder is loaded in the filmstrip; the Workbench picks the folder up as a recent folder.
You can also mark the roll folder as a **Hotstack** ([hotstack.md](hotstack.md)): EFAS then shows each picture as it lands and offers Retake and Finish Session. **Extra > Check My Scanning
Light** ([scanning-and-export-guide.md](scanning-and-export-guide.md)) reads the RAW files this makes.

## When something goes wrong

- *No camera found*: the camera's Wi-Fi and Bluetooth are on, the cable is power-only or in a hub, or another program has the camera.
- *The camera is busy*: wait a moment and try again; EFAS already retries for a few seconds on its own.
- *This lens cannot be focused from the computer*: the lens is on manual focus (move its switch to AF), or there is no lens.
- *The camera did not report a file within 60 seconds*: it may have saved the shot to the memory card; check the card and the camera's card slot setting.
- *USB error*, *the camera disconnected*: try another port without a hub, and a shorter cable; a camera that goes to sleep drops out (switch off auto power-off while scanning).
- The window gives the camera's own screen its picture back when you disconnect or close it (or close EFAS). If EFAS is ended by force the camera may need switching off and on.

## Not available

Camera-side zoom of the live picture (EDSDK does not offer it on all bodies; the loupe is software), setting the exposure from the computer, electronic shutter selection, and other makes.

## Where it is in the code

`features/tether/`: `backend.py` (what a camera must be), `edsdk_api.py` (Canon's SDK from ctypes: the constants, structures and declared signatures), `edsdk_camera.py` (the Canon
backend: one thread owns the SDK and pumps its Windows messages, pulls live pictures, drives the lens, shoots and downloads), `practice_camera.py`, `liveview.py` (decode, positive, peaking,
sharpness), `naming.py`, `session.py`. `desktop/tether_worker.py` and `desktop/view/tether_window.py` are the window.

The approach (a camera thread that owns the SDK, live pictures pulled and converted on the computer, a sharpness meter, a settle time before a non-autofocus shutter, a numbered roll) follows
the Canon EDSDK Film Scanner by Rafat Hossain (MIT, https://github.com/RafatH0ssain/Canon-EDSDK-Film-Scanner), a separate web application; EFAS's code is its own and no code was copied.
