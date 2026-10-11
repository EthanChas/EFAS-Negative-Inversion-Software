"""Fitting H&D characteristic curves: monotone interpolation, two parametric models, least squares with uncertainty, and model checks
(docs/sensitometry-tier2-design.md, sections 2.4 and 4). Numpy only; no scipy, no Qt/UI imports.

x is log10 exposure (relative or absolute), y is density above the film base, sigma is the density uncertainty of each point.
"""

import math
from dataclasses import dataclass, field

import numpy as np

DEFAULT_SIGMA = 0.01
MIN_SIGMA = 0.003
INVERSE_GRID = 4001
GOOD_CHI2, FAIR_CHI2 = 2.0, 5.0
GOOD_RUNS_P, FAIR_RUNS_P = 0.05, 0.01
SHARP_RANGE = (0.5, 200.0)
NU_RANGE = (0.05, 20.0)


class FitError(ValueError):
    """The data cannot be fitted."""


@dataclass(frozen=True)
class Samples:
    """Measured points of one curve, sorted by x. `used` marks the points the fit may use."""

    x: np.ndarray
    y: np.ndarray
    sigma: np.ndarray
    sigma_assumed: bool = False

    def __len__(self) -> int:
        return int(self.x.size)


def make_samples(x, y, sigma=None) -> Samples:
    x = np.asarray(x, dtype=np.float64).ravel()
    y = np.asarray(y, dtype=np.float64).ravel()
    if x.size != y.size:
        raise FitError("x and y need the same number of points")
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise FitError("the data contain values that are not numbers")
    assumed = sigma is None
    s = np.full(x.size, DEFAULT_SIGMA) if assumed else np.broadcast_to(np.asarray(sigma, dtype=np.float64), x.shape).copy()
    if not np.isfinite(s).all() or (s <= 0).any():
        raise FitError("uncertainties must be positive numbers")
    order = np.argsort(x, kind="stable")
    x, y, s = x[order], y[order], np.maximum(s[order], MIN_SIGMA)
    if x.size >= 2 and (np.diff(x) <= 0).any():
        raise FitError("two points have the same exposure")
    return Samples(x, y, s, assumed)


# --- monotone piecewise cubic (Fritsch and Carlson, 1980) ---------------------------------------------------------------------------------

def isotonic(y: np.ndarray, weights: np.ndarray | None = None) -> np.ndarray:
    """Pool-adjacent-violators: the closest non-decreasing sequence to y (weighted least squares)."""
    y = np.asarray(y, dtype=np.float64)
    w = np.ones_like(y) if weights is None else np.asarray(weights, dtype=np.float64)
    vals, wts, counts = [], [], []
    for yi, wi in zip(y, w):
        vals.append(yi)
        wts.append(wi)
        counts.append(1)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            tw = wts[-2] + wts[-1]
            vals[-2] = (vals[-2] * wts[-2] + vals[-1] * wts[-1]) / tw
            wts[-2] = tw
            counts[-2] += counts[-1]
            vals.pop(), wts.pop(), counts.pop()
    return np.repeat(vals, counts)


def _edge_slope(h0, h1, m0, m1) -> float:
    d = ((2 * h0 + h1) * m0 - h0 * m1) / (h0 + h1)
    if np.sign(d) != np.sign(m0):
        return 0.0
    if np.sign(m0) != np.sign(m1) and abs(d) > 3 * abs(m0):
        return 3.0 * m0
    return float(d)


class Pchip:
    """Monotone cubic interpolation through (x, y). Passes through every point and never overshoots monotone data."""

    name = "pchip"

    def __init__(self, x, y):
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        if x.size < 2 or (np.diff(x) <= 0).any():
            raise FitError("PCHIP needs at least two points with increasing x")
        self.x, self.y = x, y
        h, m = np.diff(x), np.diff(y) / np.diff(x)
        d = np.zeros_like(x)
        if x.size == 2:
            d[:] = m[0]
        else:
            for k in range(1, x.size - 1):
                if m[k - 1] * m[k] <= 0:
                    d[k] = 0.0
                else:
                    w1, w2 = 2 * h[k] + h[k - 1], h[k] + 2 * h[k - 1]
                    d[k] = (w1 + w2) / (w1 / m[k - 1] + w2 / m[k])
            d[0] = _edge_slope(h[0], h[1], m[0], m[1])
            d[-1] = _edge_slope(h[-1], h[-2], m[-1], m[-2])
        self.d, self.h, self.m = d, h, m

    def _locate(self, q):
        q = np.asarray(q, dtype=np.float64)
        return q, np.clip(np.searchsorted(self.x, q, side="right") - 1, 0, self.x.size - 2)

    def __call__(self, q):
        q, i = self._locate(q)
        qc = np.clip(q, self.x[0], self.x[-1])
        t = (qc - self.x[i]) / self.h[i]
        h00, h10 = 2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t
        h01, h11 = -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2
        return h00 * self.y[i] + h10 * self.h[i] * self.d[i] + h01 * self.y[i + 1] + h11 * self.h[i] * self.d[i + 1]

    def derivative(self, q):
        q, i = self._locate(q)
        qc = np.clip(q, self.x[0], self.x[-1])
        t = (qc - self.x[i]) / self.h[i]
        dh00, dh10 = 6 * t ** 2 - 6 * t, 3 * t ** 2 - 4 * t + 1
        dh01, dh11 = -6 * t ** 2 + 6 * t, 3 * t ** 2 - 2 * t
        out = (dh00 * self.y[i] + dh01 * self.y[i + 1]) / self.h[i] + dh10 * self.d[i] + dh11 * self.d[i + 1]
        return np.where((q < self.x[0]) | (q > self.x[-1]), 0.0, out)

    def support(self) -> tuple[float, float]:
        return float(self.x[0]), float(self.x[-1])


# --- parametric models --------------------------------------------------------------------------------------------------------------------

def _exp(v) -> float:
    """exp that cannot overflow, so a runaway trial step in the optimiser stays a finite (bad) trial."""
    return math.exp(max(-25.0, min(25.0, float(v))))


def _sigmoid(z):
    return 0.5 * (1.0 + np.tanh(0.5 * np.asarray(z, dtype=np.float64)))


def _softplus(z):
    return np.logaddexp(0.0, z)


class SoftplusCurve:
    """Density above base: a straight line of slope gamma bounded below at 0 and above at Dmax by softplus knees (toe and shoulder sharpness).
    The raw knee construction dips a little below 0 when the shoulder is soft, so the result is rescaled to span exactly 0 to Dmax."""

    name = "softplus"
    params = ("gamma", "x0", "dmax", "toe", "shoulder")

    def __init__(self, gamma, x0, dmax, toe, shoulder):
        self.gamma, self.x0, self.dmax = float(gamma), float(x0), float(dmax)
        self.toe = float(np.clip(toe, *SHARP_RANGE))
        self.shoulder = float(np.clip(shoulder, *SHARP_RANGE))
        self._low = -float(_softplus(-self.shoulder * self.dmax)) / self.shoulder
        self._scale = self.dmax / (self.dmax - self._low)

    def _v(self, x):
        return self.dmax / 2.0 + self.gamma * (np.asarray(x, dtype=np.float64) - self.x0)

    def __call__(self, x):
        v = self._v(x)
        v1 = _softplus(self.toe * v) / self.toe
        raw = self.dmax - _softplus(self.shoulder * (self.dmax - v1)) / self.shoulder
        return (raw - self._low) * self._scale

    def derivative(self, x):
        v = self._v(x)
        v1 = _softplus(self.toe * v) / self.toe
        return self._scale * self.gamma * _sigmoid(self.toe * v) * _sigmoid(self.shoulder * (self.dmax - v1))

    def values(self) -> dict[str, float]:
        return {"gamma": self.gamma, "x0": self.x0, "dmax": self.dmax, "toe": self.toe, "shoulder": self.shoulder}

    @staticmethod
    def to_theta(p: dict) -> np.ndarray:
        return np.array([math.log(p["gamma"]), p["x0"], math.log(p["dmax"]), math.log(p["toe"]), math.log(p["shoulder"])])

    @staticmethod
    def from_theta(t) -> "SoftplusCurve":
        return SoftplusCurve(_exp(t[0]), t[1], _exp(t[2]), _exp(t[3]), _exp(t[4]))

    @staticmethod
    def jacobian_scale(p: dict) -> np.ndarray:
        """d(parameter)/d(theta) for the log-transformed parameters, used to turn theta uncertainties into parameter uncertainties."""
        return np.array([p["gamma"], 1.0, p["dmax"], p["toe"], p["shoulder"]])


class RichardsCurve:
    """Density above base as a generalised logistic: dmax * s^(1/nu), s = 1/(1 + exp(-B (x - xm))). nu = 1 is the plain logistic; nu != 1 makes the toe and shoulder unequal."""

    name = "richards"
    params = ("dmax", "rate", "xm", "nu")

    def __init__(self, dmax, rate, xm, nu):
        self.dmax, self.rate, self.xm = float(dmax), float(rate), float(xm)
        self.nu = float(np.clip(nu, *NU_RANGE))

    def _s(self, x):
        return _sigmoid(self.rate * (np.asarray(x, dtype=np.float64) - self.xm))

    def __call__(self, x):
        return self.dmax * self._s(x) ** (1.0 / self.nu)

    def derivative(self, x):
        s = self._s(x)
        return self.dmax * (self.rate / self.nu) * s ** (1.0 / self.nu) * (1.0 - s)

    def values(self) -> dict[str, float]:
        return {"dmax": self.dmax, "rate": self.rate, "xm": self.xm, "nu": self.nu}

    @staticmethod
    def to_theta(p: dict) -> np.ndarray:
        return np.array([math.log(p["dmax"]), math.log(p["rate"]), p["xm"], math.log(p["nu"])])

    @staticmethod
    def from_theta(t) -> "RichardsCurve":
        return RichardsCurve(_exp(t[0]), _exp(t[1]), t[2], _exp(t[3]))

    @staticmethod
    def jacobian_scale(p: dict) -> np.ndarray:
        return np.array([p["dmax"], p["rate"], 1.0, p["nu"]])


MODELS = {"softplus": SoftplusCurve, "richards": RichardsCurve}


# --- Levenberg-Marquardt ------------------------------------------------------------------------------------------------------------------

def _jacobian(fun, theta, step=1e-6):
    base = fun(theta)
    cols = []
    for j in range(theta.size):
        h = step * max(1.0, abs(theta[j]))
        up, dn = theta.copy(), theta.copy()
        up[j] += h
        dn[j] -= h
        cols.append((fun(up) - fun(dn)) / (2 * h))
    return base, np.stack(cols, axis=1)


def levenberg_marquardt(residuals, theta0, max_iter: int = 300, tol: float = 1e-11):
    """Minimise sum(residuals(theta)^2). Returns (theta, jacobian at the solution, cost, converged)."""
    theta = np.asarray(theta0, dtype=np.float64).copy()
    lam = 1e-3
    r, J = _jacobian(residuals, theta)
    cost = float(r @ r)
    converged = False
    for _ in range(max_iter):
        A, g = J.T @ J, J.T @ r
        improved = False
        for _try in range(30):
            try:
                step = np.linalg.solve(A + lam * np.diag(np.maximum(np.diag(A), 1e-12)), -g)
            except np.linalg.LinAlgError:
                lam *= 10
                continue
            trial = theta + step
            rt = residuals(trial)
            ct = float(rt @ rt)
            if np.isfinite(ct) and ct < cost:
                improved = True
                lam = max(lam / 5, 1e-12)
                break
            lam *= 5
        if not improved:
            converged = True
            break
        done = cost - ct <= tol * (1.0 + cost)
        theta = trial
        cost = ct
        r, J = _jacobian(residuals, theta)
        if done:
            converged = True
            break
    return theta, J, cost, converged


def _initial_guesses(x, y, name):
    ymax = float(max(y.max(), 0.05))
    slope = np.gradient(y, x) if x.size > 2 else np.array([np.ptp(y) / max(np.ptp(x), 1e-9)])
    g0 = float(max(slope.max(), 0.05))
    mid = float(np.interp(ymax / 2.0, np.maximum.accumulate(y), x)) if np.ptp(y) > 0 else float(x.mean())
    if name == "softplus":
        return [dict(gamma=g0, x0=mid, dmax=ymax * f, toe=a, shoulder=b) for f in (1.05, 1.3) for a in (3.0, 10.0, 30.0) for b in (3.0, 10.0, 30.0)]
    return [dict(dmax=ymax * f, rate=4.0 * g0 / ymax * k, xm=mid, nu=nu) for f in (1.1, 1.4) for k in (0.6, 1.0, 1.6) for nu in (0.5, 1.0, 2.5)]


# --- results ------------------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ParametricFit:
    model: str
    params: dict
    std_errors: dict
    curve: object
    rms: float
    max_abs: float
    chi2_red: float
    runs_p: float
    loo_rms: float
    dof: int
    quality: str
    reasons: tuple[str, ...]
    cov: np.ndarray | None = field(default=None, repr=False)
    theta: np.ndarray | None = field(default=None, repr=False)

    def band(self, x, z: float = 1.96) -> np.ndarray:
        """Half-width of the confidence band for the fitted curve at x, by propagating the parameter covariance."""
        x = np.asarray(x, dtype=np.float64)
        if self.cov is None or self.theta is None:
            return np.zeros_like(x)
        cls = MODELS[self.model]
        eps = 1e-6
        grads = []
        for j in range(self.theta.size):
            up, dn = self.theta.copy(), self.theta.copy()
            h = eps * max(1.0, abs(self.theta[j]))
            up[j] += h
            dn[j] -= h
            grads.append((cls.from_theta(up)(x) - cls.from_theta(dn)(x)) / (2 * h))
        G = np.stack(grads, axis=-1)
        var = np.einsum("...i,ij,...j->...", G, self.cov, G)
        return z * np.sqrt(np.maximum(var, 0.0))


@dataclass(frozen=True)
class FitReport:
    samples: Samples
    pchip: Pchip
    fits: dict
    chosen: str
    support: tuple[float, float]
    notes: tuple[str, ...]

    def curve(self, name: str | None = None):
        name = name or self.chosen
        return self.pchip if name == "pchip" else self.fits[name].curve

    def residuals(self, name: str | None = None) -> np.ndarray:
        return self.samples.y - self.curve(name)(self.samples.x)


def runs_test_p(residuals: np.ndarray) -> float:
    """Wald-Wolfowitz runs test on the signs of the residuals. A small p means the residuals have a systematic pattern (the model has the wrong shape)."""
    signs = residuals[np.abs(residuals) > 1e-6] > 0  # residuals a millionth of the uncertainty are rounding, not a pattern (noise-free data would otherwise get random signs)
    n1, n2 = int(signs.sum()), int((~signs).sum())
    if n1 == 0 or n2 == 0 or n1 + n2 < 6:
        return 1.0
    runs = 1 + int((signs[1:] != signs[:-1]).sum())
    mu = 2.0 * n1 * n2 / (n1 + n2) + 1.0
    var = (mu - 1.0) * (mu - 2.0) / (n1 + n2 - 1.0)
    if var <= 0:
        return 1.0
    return float(math.erfc(abs(runs - mu) / math.sqrt(var) / math.sqrt(2.0)))


def _fit_one(name, x, y, s):
    cls = MODELS[name]

    def resid(theta):
        return (y - cls.from_theta(theta)(x)) / s

    best = None
    for guess in _initial_guesses(x, y, name):
        try:
            theta, J, cost, ok = levenberg_marquardt(resid, cls.to_theta(guess))
        except (FloatingPointError, ValueError, OverflowError):
            continue
        if np.isfinite(cost) and (best is None or cost < best[2]):
            best = (theta, J, cost, ok)
    return best


def _loo_rms(name, x, y, s, theta_full):
    cls = MODELS[name]
    errs = []
    for k in range(x.size):
        keep = np.arange(x.size) != k

        def resid(theta, keep=keep):
            return (y[keep] - cls.from_theta(theta)(x[keep])) / s[keep]

        try:
            theta, _J, cost, _ok = levenberg_marquardt(resid, theta_full, max_iter=80)
            errs.append(float(y[k] - cls.from_theta(theta)(x[k])))
        except (FloatingPointError, ValueError):
            errs.append(float("nan"))
    errs = np.array(errs)
    return float(np.sqrt(np.nanmean(errs ** 2))) if np.isfinite(errs).any() else float("inf")


def fit_parametric(samples: Samples, name: str) -> ParametricFit | None:
    """Fit one model. None when there are too few points for its parameters."""
    cls = MODELS[name]
    p = len(cls.params)
    n = len(samples)
    if n < p + 2:
        return None
    x, y, s = samples.x, samples.y, samples.sigma
    found = _fit_one(name, x, y, s)
    if found is None:
        return None
    theta, J, cost, converged = found
    curve = cls.from_theta(theta)
    resid = y - curve(x)
    dof = n - p
    chi2_red = cost / dof
    inflate = max(1.0, chi2_red)
    try:
        cov_theta = inflate * np.linalg.inv(J.T @ J)
    except np.linalg.LinAlgError:
        cov_theta = np.full((p, p), np.inf)
    values = curve.values()
    scale = cls.jacobian_scale(values)
    sd = np.sqrt(np.maximum(np.diag(cov_theta), 0.0)) * scale
    runs_p = runs_test_p(resid)
    loo = _loo_rms(name, x, y, s, theta)
    reasons = []
    if not converged:
        reasons.append("the fit did not settle")
    if not np.isfinite(sd).all():
        reasons.append("the data do not pin down every parameter")
    if chi2_red > FAIR_CHI2:
        reasons.append(f"the fit misses the points by about {math.sqrt(chi2_red):.1f} times the stated uncertainty")
    elif chi2_red > GOOD_CHI2:
        reasons.append("the fit is somewhat looser than the stated uncertainty")
    if runs_p < FAIR_RUNS_P:
        reasons.append("the residuals have a systematic pattern: the model shape does not match the curve")
    elif runs_p < GOOD_RUNS_P:
        reasons.append("the residuals show a hint of a systematic pattern")
    at_bound = [k for k, v in values.items() if (k in ("toe", "shoulder") and (v <= SHARP_RANGE[0] * 1.001 or v >= SHARP_RANGE[1] * 0.999)) or (k == "nu" and (v <= NU_RANGE[0] * 1.001 or v >= NU_RANGE[1] * 0.999))]
    if at_bound:
        reasons.append(f"{', '.join(at_bound)} reached its limit: the data cannot determine it")
    if not converged or not np.isfinite(sd).all() or chi2_red > FAIR_CHI2 or runs_p < FAIR_RUNS_P:
        quality = "poor"
    elif chi2_red > GOOD_CHI2 or runs_p < GOOD_RUNS_P or at_bound:
        quality = "fair"
    else:
        quality = "good"
    return ParametricFit(
        name, values, dict(zip(cls.params, (float(v) for v in sd))), curve, float(np.sqrt(np.mean(resid ** 2))), float(np.abs(resid).max()), float(chi2_red),
        runs_p, loo, int(dof), quality, tuple(reasons), cov_theta, theta,
    )


def fit_curve(x, y, sigma=None, models=("softplus", "richards"), monotone: bool = True) -> FitReport:
    """Fit a measured curve three ways (PCHIP, softplus, Richards) and recommend one. The parametric fits are only recommended when they pass
    the quality checks and have the lowest leave-one-out error; otherwise the recommendation is PCHIP, which makes no shape assumption."""
    samples = make_samples(x, y, sigma)
    if len(samples) < 3:
        raise FitError("A curve needs at least 3 points")
    notes = []
    if samples.sigma_assumed:
        notes.append(f"No point uncertainties were given, so {DEFAULT_SIGMA:g} density was assumed for every point.")
    ys = samples.y
    if monotone and (np.diff(ys) < 0).any():
        ys = isotonic(ys, 1.0 / samples.sigma ** 2)
        notes.append("The densities were not rising with exposure everywhere; they were made monotone (pool adjacent violators) before interpolating.")
    pchip = Pchip(samples.x, ys)
    fits = {}
    for name in models:
        f = fit_parametric(samples, name)
        if f is None:
            notes.append(f"Too few points for the {name} model ({len(MODELS[name].params)} parameters).")
        else:
            fits[name] = f
    usable = {k: f for k, f in fits.items() if f.quality in ("good", "fair")}
    chosen = min(usable, key=lambda k: usable[k].loo_rms) if usable else "pchip"
    if not usable and fits:
        notes.append("No parametric model passed the quality checks, so the interpolated curve is recommended.")
    return FitReport(samples, pchip, fits, chosen, (float(samples.x[0]), float(samples.x[-1])), tuple(notes))


def invert_curve(curve, y, x_lo: float, x_hi: float):
    """The exposure at which `curve` reaches each density in y, within [x_lo, x_hi]. Returns (x, status) where status is -1 below the curve's
    value at x_lo, +1 above its value at x_hi, 0 inside. Out-of-range densities are clamped to the ends, never extrapolated."""
    grid = np.linspace(x_lo, x_hi, INVERSE_GRID)
    vals = np.maximum.accumulate(curve(grid))
    y = np.asarray(y, dtype=np.float64)
    x = np.interp(y, vals, grid)
    status = np.where(y < vals[0], -1, np.where(y > vals[-1], 1, 0)).astype(np.int8)
    return x, status
