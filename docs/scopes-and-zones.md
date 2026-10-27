# Waveform, Parade, Vectorscope and the Zone map

Other ways to read a picture than the histogram, after the analysis views NegPy added in 0.64 and 0.65. They are drawn from the picture on the screen, so they follow every edit.

**The graph choice.** Above the histogram (the White Balance (EFAS) panel) a row of four buttons picks the graph: **Histogram**, **Waveform**, **Parade** or **Vector**. The other buttons in that panel (Exposure, Color, Log, Split, the clipping buttons) belong to the histogram.

- **Waveform.** The picture laid out as it is across: each column of the graph holds the brightness values of that column of the picture, from 0 at the bottom to 255 at the top. A bright sky is a high trace on the left, a dark foreground a low one. It shows at once how much of the tonal range a picture uses and whether anything touches the top or the bottom.
- **Parade.** The red, green and blue waveforms side by side. A colour cast is one channel sitting above or below the other two: for a neutral scene the three traces should match in height.
- **Vector (vectorscope).** Every pixel plotted by hue (the angle) and saturation (the distance from the middle). Grey is the centre. R, Y, G, C, B and M mark where the primaries and secondaries at 75% saturation fall; the dashed line is where skin tones fall, so a portrait's colour sits along it.

**Zones.** The **Zones** button beside Peaking colours the picture by brightness in eleven zones, 0 (black) to X (white) with V as the middle grey: violet and blues for the shadows, teal and grey for the middle, yellows and oranges for the highlights, red and white at the top. It shows at a glance what is crushed, what is a middle tone and what is blown; hover the button for each zone's share of the picture. It is a view only: nothing is changed in the photo.

The scopes read the picture at no more than 480 columns, which is plenty for the shape; the zone map is made at the picture's own size. The Shadow and Highlight Clipping buttons (marks on the picture) were there already.
