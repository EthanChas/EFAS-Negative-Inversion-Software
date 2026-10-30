# Negative Carrier

In the darkroom a negative carrier whose aperture has been **filed out** larger than the frame prints the film's own rebate: the dark edge of the film between the picture and the filed metal, and past the metal a margin of bare paper. The edge is never clean. The film gate that holds the film is a little uneven, the filed aperture is ragged (file strokes, nicks, rounded corners), and light flares off the bevel of the metal. Printers use this as a signature: it proves the whole frame was printed.

**Finishing > Negative Carrier** simulates it. It is a port of NegPy's filed carrier (`features/carrier/logic.py`; NegPy is GPL-3, the same licence as EFAS).

- **Width (mm):** how wide the rebate prints, in mm on a 30 cm print (0 to 5; 0 is off). It scales with the picture, so a preview and a full-size export look the same.
- **Rough:** how ragged the filed edge is.
- **Corner:** how round the corners of the filed aperture are.
- **Flare:** the bright line light makes along the filed bevel (0 is none).

The pattern is **fixed**: one filed carrier for every frame, from a fixed seed, so the same photo always prints the same edge, a preview matches its export, and a picture and its copy match. It works on the finished, cropped picture, after the vignette and before the watermark and the border, and the picture is composited in linear light over the bare paper, which is white. The filed edge and the flare are exposure: the more of the paper is exposed, the darker it prints.

What it does not do: NegPy tones the rebate through the print's own curves, so on a toned or split-toned print the rebate takes the print's black. Here the rebate is plain light, paper to black. It is a finish, not a measurement: it adds pixels that were not in the scan.
