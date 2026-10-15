# Film crosstalk profiles

The sixteen `.toml` files here are the colour-negative crosstalk matrices from the NegPy project's profile gallery (NegPy 0.56.0, <https://github.com/marcinz606/NegPy>, `crosstalk/`), included under the GNU General Public License v3.0, the licence NegPy and EFAS share. They are bundled unchanged.

Each is a 3x3 matrix (rows out red / green / blue, columns in red / green / blue) for unmixing a negative's dye densities, read off a stock's published spectral dye-density curves. They are approximations of the dyes alone ("(approx)" in the names), not measurements of any scanning setup: the light and the sensor mix channels too. EFAS applies them in density, blended with the identity by the Crosstalk slider and with every row summing to 1 so greys stay grey (see `docs/film-and-paper-conversion.md`).

Your own profiles go in `crosstalk/` inside the EFAS data folder, in the same format:

```toml
name = "My film and light"
matrix = [
  [ 1.00, -0.05, -0.02],
  [-0.04,  1.00, -0.08],
  [-0.01, -0.10,  1.00],
]
```
