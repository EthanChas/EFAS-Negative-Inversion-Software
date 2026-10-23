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

**Picture and zoom.** The window opens wide (up to 1640 by 940, and no bigger than your screen) and the live picture is shown at the camera's own size, up to 1280 pixels wide (a Canon live
picture is 960 to 1620 wide, so most are shown whole); it is shrunk with area averaging when the window is smaller, and shown as square pixels when you zoom in a lot, so you can judge them. The
**Zoom** slider under the picture goes from 100% (the whole picture fitted to the window) to 800%; the mouse wheel zooms about the pointer, dragging moves the zoomed picture, **Fit** (or the key `0`) goes back, and a
plain click still measures sharpness where you click. The zoom is software: it enlarges what the camera sends. The conversion's table is still worked out from a picture 800 wide, so the colours do not
change with the size shown.

**Exposure.** The camera's mode, and its **ISO**, **Aperture**, **Shutter speed** and **Exposure compensation**, read from the camera (and read again every few seconds, so a turned dial shows). Each
box lists only what the camera will take just now, in thirds of a stop: with the mode dial on **M** (manual) ISO, aperture and shutter speed can be set from the window; on Av or Tv the camera sets one of
them itself and its box is greyed, and the panel says to turn the dial to M. **Auto exposure** (it needs M or Tv) meters the film in the live picture, leaving out the black holder and the bare light of
the sprocket holes, finds the brightest colour of the film (the clear base between and around the frames, which is the brightest film on a negative), and moves the **shutter speed** until that sits
just short of clipping (a live-picture value of about 235 of 255, within about a sixth of a stop), reading again after every change because the live picture lags a few frames behind. The base is
what is kept from clipping because the conversion needs its colour to take out the orange mask; the picture, being denser, then comes out as bright as it can without losing the base. The aperture and ISO
are left alone: on a copy stand the aperture is the lens's sharp one and the ISO the quiet one. If the shutter reaches the end of its range it says so and which other setting to change. The
practice camera has the same controls: its picture gets brighter with more light and clips, so auto exposure can be tried without a camera. Written against Canon's property codes (each code is an eighth
of a stop) and a stand-in, not yet tried on a real body.

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

Camera-side zoom of the live picture (EDSDK does not offer it on all bodies; the zoom and the loupe are software, so they enlarge the pixels the camera sends and show no more detail than they hold), exposure compensation in auto exposure, exposure from the computer on a body whose dial is not on M, electronic shutter selection, and other makes.

## Where it is in the code

`features/tether/`: `backend.py` (what a camera must be), `edsdk_api.py` (Canon's SDK from ctypes: the constants, structures and declared signatures), `edsdk_camera.py` (the Canon
backend: one thread owns the SDK and pumps its Windows messages, pulls live pictures, drives the lens, shoots and downloads), `practice_camera.py`, `exposure.py` (the camera's exposure codes as words, and the auto exposure arithmetic), `liveview.py` (decode, positive, peaking,
sharpness), `naming.py`, `session.py`. `desktop/tether_worker.py` and `desktop/view/tether_window.py` are the window.

The approach (a camera thread that owns the SDK, live pictures pulled and converted on the computer, a sharpness meter, a settle time before a non-autofocus shutter, a numbered roll) follows
the Canon EDSDK Film Scanner by Rafat Hossain (MIT, https://github.com/RafatH0ssain/Canon-EDSDK-Film-Scanner), a separate web application; EFAS's code is its own and no code was copied.

## Camera zoom: more pixels in the live picture

Canon's SDK sends a live picture that is only 960 x 640 on many bodies (up to 1620 wide on newer ones), so the **Zoom** slider under the picture can only make those pixels bigger. **Camera zoom** (Fit, 5x, 10x, under the slider) asks the camera itself to zoom its live view: it then sends the middle of the sensor at the same picture size, so at 5x or 10x the film's grain and fine detail arrive as real pixels, which is what you need to judge focus. The sharpness reading starts over when you change it (it is a different picture). The buttons are on as soon as the camera is live (a body only answers for `Evf_Zoom` once live view runs, so EFAS no longer asks first: it just tries, and shows the camera's own answer if it refuses). It starts on the middle of the sensor; **drag with the middle mouse button** to move around in the zoomed picture (it moves the camera's own zoom frame, `Evf_ZoomPosition`, so you can look over the whole film; there are no buttons for it). The middle button also moves our own Zoom-slider picture when the camera is not zoomed. The live picture is no longer made smaller than the camera sent it (up to 1620 wide; peaking is still worked out at 960 wide and stretched over it).

## Flat field: an even preview

The light behind the film is never perfectly even, so the live picture is brighter in the middle and darker at the corners, which makes it hard to see whether the *film* is even or flat. The **Flat field** box (under View) fixes the preview with EFAS's own flat field (`features/flatfield`, the same gain map and the same method you chose in the Flat Field panel):

1. Take the film out so the camera sees only the bare light, and set the exposure so it is bright but not white.
2. Click **Capture the light**. Eight live pictures are averaged into a flat field, which is kept in `~/.EFAS/tether-flat-field.npz` and loaded again next time. (A picture that is too dark, or blown out, is refused with what to change.)
3. **Even out the preview with a flat field** switches it on and off. **Use EFAS's flat field** uses the permanent flat field from the Flat Field panel instead, when there is one and it is switched on. **Forget** stops using it and throws the captured one away.

It only changes the preview (and the loupe, and the colour you pick for the clear film): the sharpness meter and the clipping warning measure the camera's own picture, and the shots the camera saves are corrected by the flat field in the editor, as before. It is of the whole picture, so it switches itself off while the camera's own zoom is on.

