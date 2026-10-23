# Grade Sharpness: is the shot in focus?

**File > Grade Sharpness...** grades how sharp each frame of the open folder is, keeps the grade, marks each tile of the filmstrip with its score, and can show which part of a frame was measured. It grades the *shot* (is what you focused on in focus?), not the scan, and it changes nothing: no frame is rejected, flagged or edited for you. It is ported from the Scan Grading of the author's modified NegPy.

## The window

- **Grade Entire Roll** grades every frame that has no grade yet, one at a time in the background (each frame is read in turn, so a long roll takes a while; **Stop** ends it early and keeps what is done).
- **Grade All Again** throws the grades away and grades every frame afresh. **Grade the Open Frame** grades just the photo open in the editor again.
- The list shows each frame's **result** (Sharp, Soft or Blurred) and its **score** from 0 to 100; the heading counts them. Double-click a frame to open it in the editor.
- **Show Where It Was Measured...** (with a frame selected) opens it with red (soft) through amber to green (sharp) laid over the parts that were judged, and plain gray everywhere else, since no verdict was reached there. Hover for the exact value under the pointer; **Show Original** switches the colours off.

A grade is kept between sessions in the edit database, tied to the file as it is (its size and time): a file that is changed or replaced is graded afresh. The filmstrip's tiles show it as a small chip at the top left (green sharp, amber soft, red blurred, with the score), and **Show > Soft or blurred (graded)** in the filmstrip lists only the soft ones.

## What is measured

A **re-blur test**, after Crete et al., "The Blur Effect": the frame is blurred a second time and the edges are checked for how much of their contrast survives. A sharp frame changes a great deal under a second blur; an already soft one barely changes at all. The comparison is against the frame's own content, so the score means the same for completely different scenes, with no reference picture.

- It is measured only on the **strongest 5% of the edges**, on a denoised copy, so grain and sensor noise cannot fake an edge and an intentionally soft background (a portrait, a bird against open sky) does not drag a correctly focused frame down.
- It takes the **worse of the horizontal and the vertical** direction, so blur in one direction (the camera moved) counts.
- A margin of 4% at every edge is left out: the scan's own border and rebate is a stark edge that is not part of the picture.
- Below **60** a frame is **Soft**, below **38 Blurred**. These limits were found against a real photo library: scores fall steadily as a frame is blurred and agree with frames checked by hand.
- A frame with no edge to judge at all (an empty or featureless picture) is Blurred with a score of 0.

The frame is read at reduced size (a RAW at half size, with the camera's own white balance and no brightening) and judged at 700 pixels on its long side, so a roll grades quickly and the grade is of the negative as scanned, not of a converted positive.

## Limits

- It judges what is *in* the frame. A frame that is truly empty, or all one tone, is graded Blurred whether or not it is in focus.
- Very heavy grain on a very blurred frame can score higher than it should, because noise looks like edges. At the grain of a real scan (the frame is shrunk to 700 pixels, which averages most of it away) a blurred frame still comes out Blurred.
- The grade is of the whole frame's strongest edges. A frame with the subject sharp and everything else soft is graded on the subject; a landscape with no single subject may be judged more harshly than you would judge it.

Code: `features/sharpgrade/logic.py` (the grade and the overlay, no Qt), `processor.py` (reading a frame in), `desktop/sharpness_worker.py` (the background thread), `desktop/view/sharpness_dialog.py` (the window and the overlay), `features/persistence/edit_store.py` (`sharpness_grades`).
