"""Functions to find fields on the next step of plasma evolution."""
import numpy as np

import scipy.fftpack

from ..config.config import Config
from .data import Fields, Currents, Const_Arrays


# Solving Laplace equation with Dirichlet boundary conditions (Ez and Phi) #

def calculate_Ez(grid_step_size, const: Const_Arrays, currents: Currents):
    """
    Calculate Ez as iDST2D(dirichlet_matrix * DST2D(djx/dx + djy/dy)).
    """
    # 0. Calculate RHS (NOTE: it is smaller by 1 on each side).
    # NOTE: use gradient instead if available (cupy doesn't have gradient yet).
    jx, jy = currents.jx, currents.jy

    djx_dx = jx[2:, 1:-1] - jx[:-2, 1:-1]
    djy_dy = jy[1:-1, 2:] - jy[1:-1, :-2]
    rhs_inner = -(djx_dx + djy_dy) / (grid_step_size * 2)  # -?

    # 1. Apply DST-Type1-2D (Discrete Sine Transform Type 1 2D) to the RHS.
    f = scipy.fftpack.dstn(rhs_inner, type=1)

    # 2. Multiply f by the special matrix that does the job and normalizes.
    f *= const.dirichlet_matrix

    # 3. Apply iDST-Type1-2D (Inverse Discrete Sine Transform Type 1 2D).
    #    We don't have to define a separate iDST function, because
    #    unnormalized DST-Type1 is its own inverse, up to a factor 2(N+1)
    #    and we take all scaling matters into account with a single factor
    #    hidden inside dirichlet_matrix.

    Ez_inner = scipy.fftpack.dstn(f, type=1)
    Ez = np.pad(Ez_inner, 1, 'constant', constant_values=0)
    return Ez


def calculate_Phi(const: Const_Arrays, currents: Currents):
    """
    Calculates Phi as iDST2D(dirichlet_matrix * DST2D(-ro + jz)).
    """
    ro, jz = currents.ro, currents.jz

    rhs_inner = (ro - jz)[1:-1, 1:-1]

    f = scipy.fftpack.dstn(rhs_inner, type=1)

    f *= const.dirichlet_matrix

    Phi_inner = scipy.fftpack.dstn(f, type=1)
    Phi = np.pad(Phi_inner, 1, 'constant', constant_values=0)

    return Phi


# Solving Laplace or Helmholtz equation with mixed boundary conditions #

def mix2d(a):
    """
    Calculate a DST-DCT-hybrid transform
    (DST in first direction, DCT in second one).
    """
    # NOTE: LCODE 3D uses x as the first direction, thus the confision below.
    a_dst     = scipy.fftpack.dst(a,     type=1, axis=0)
    a_dst_dct = scipy.fftpack.dct(a_dst, type=1, axis=1)
    # add zeros in top and bottom
    a_out = np.pad(a_dst_dct, ((1,1),(0,0)), 'constant', constant_values=0)
    return a_out


def dx_dy(arr, grid_step_size):
    """
    Calculate x and y derivatives simultaneously (like np.gradient does).
    NOTE: use gradient instead if available (cupy doesn't have gradient yet).
    NOTE: arrays are assumed to have zeros on the perimeter.
    """
    dx, dy = np.zeros_like(arr), np.zeros_like(arr)
    dx[1:-1, 1:-1] = arr[2:, 1:-1] - arr[:-2, 1:-1]  # arrays have 0s
    dy[1:-1, 1:-1] = arr[1:-1, 2:] - arr[1:-1, :-2]  # on the perimeter
    return dx / (grid_step_size * 2), dy / (grid_step_size * 2)


def calculate_Ex_Ey_Bx_By(
    grid_step_size, xi_step_size, trick, variant_A, const: Const_Arrays,
    fields_avg: Fields, ro_beam_full, ro_beam_prev, currents_full: Currents,
    currents_prev: Currents
):
    """
    Calculate transverse fields as iDST-DCT(mixed_matrix * DST-DCT(RHS.T)).T,
    with and without transposition depending on the field component.
    NOTE: density and currents are assumed to be zero on the perimeter
          (no plasma particles must reach the wall, so the reflection boundary
           must be closer to the center than the simulation window boundary
           minus the coarse plasma particle cloud width).
    """
    jx_prev, jy_prev = currents_prev.jx, currents_prev.jy
    jx,      jy      = currents_full.jx, currents_full.jy

    ro = (currents_full.ro + ro_beam_full +
               currents_prev.ro + ro_beam_prev) / 2
    jz = (currents_full.jz + ro_beam_full +
               currents_prev.jz + ro_beam_prev) / 2

    # 1. Calculate gradients and RHS.
    dro_dx, dro_dy = dx_dy(ro, grid_step_size)
    djz_dx, djz_dy = dx_dy(jz, grid_step_size)
    djx_dxi = (jx_prev - jx) / xi_step_size  # - ?
    djy_dxi = (jy_prev - jy) / xi_step_size  # - ?

    # Are we solving a Laplace equation or a Helmholtz one?
    Ex_rhs = -((dro_dx - djx_dxi) - fields_avg.Ex * trick)  # -?
    Ey_rhs = -((dro_dy - djy_dxi) - fields_avg.Ey * trick)
    Bx_rhs = +((djz_dy - djy_dxi) + fields_avg.Bx * trick)
    By_rhs = -((djz_dx - djx_dxi) - fields_avg.By * trick)

    # Boundary conditions application (for future reference, ours are zero):
    # rhs[:, 0] -= bound_bottom[:] * (2 / grid_step_size)
    # rhs[:, -1] += bound_top[:] * (2 / grid_step_size)

    # 2. Apply our mixed DCT-DST transform to RHS.
    Ey_f = mix2d(Ey_rhs[1:-1, :])[1:-1, :]

    # 3. Multiply f by the magic matrix.
    mix_mat = const.field_mixed_matrix
    Ey_f *= mix_mat

    # 4. Apply our mixed DCT-DST transform again.
    Ey = mix2d(Ey_f)

    # Likewise for other fields:
    Bx = mix2d(mix_mat * mix2d(Bx_rhs[1:-1, :])[1:-1, :])
    By = mix2d(mix_mat * mix2d(By_rhs.T[1:-1, :])[1:-1, :]).T
    Ex = mix2d(mix_mat * mix2d(Ex_rhs.T[1:-1, :])[1:-1, :]).T

    return Ex, Ey, Bx, By


# Pushing particles without any fields (used for initial halfstep estimation) #

def calculate_Bz(grid_step_size, const: Const_Arrays, currents: Currents):
    """
    Calculate Bz as iDCT2D(dirichlet_matrix * DCT2D(djx/dy - djy/dx)).
    """
    # 0. Calculate RHS.
    # NOTE: use gradient instead if available (cupy doesn't have gradient yet).    
    jx, jy = currents.jx, currents.jy

    djx_dy = jx[1:-1, 2:] - jx[1:-1, :-2]
    djy_dx = jy[2:, 1:-1] - jy[:-2, 1:-1]
    djx_dy = np.pad(djx_dy, 1, 'constant', constant_values=0)
    djy_dx = np.pad(djy_dx, 1, 'constant', constant_values=0)
    rhs = -(djx_dy - djy_dx) / (grid_step_size * 2)  # -?

    # As usual, the boundary conditions are zero
    # (otherwise add them to boundary cells, divided by grid_step_size/2

    # 1. Apply DST-Type1-2D (Discrete Sine Transform Type 1 2D) to the RHS.
    f = scipy.fftpack.dctn(rhs, type=1)

    # 2. Multiply f by the special matrix that does the job and normalizes.
    f *= const.neumann_matrix

    # 3. Apply iDCT-Type1-2D (Inverse Discrete Cosine Transform Type 1 2D).
    #    We don't have to define a separate iDCT function, because
    #    unnormalized DCT-Type1 is its own inverse, up to a factor 2(N+1)
    #    and we take all scaling matters into account with a single factor
    #    hidden inside neumann_matrix.
    Bz: np.ndarray = scipy.fftpack.dctn(f, type=1)

    Bz -= Bz.mean()  # Integral over Bz must be 0.

    return Bz


class FieldComputer(object):
    """
    Class to store some parameters for fields computing.

    Parameters
    ----------
    config : ..config.Config

    Attributes
    ----------
    grid_step_size : float
        Plane grid step size.

    """
    def __init__(self, config: Config):
        self.grid_step_size = config.getfloat('window-width-step-size')
        self.xi_step_size = config.getfloat('xi-step')
        self.trick = config.getfloat('field-solver-subtraction-trick')
        self.variant_A = config.getbool('field-solver-variant-A')

    def compute_fields(
        self, fields: Fields, flds_prev: Fields, const: Const_Arrays,
        rho_beam_full, rho_beam_prev, currents_prev: Currents,
        currents_full: Currents
    ):
        # Looks terrible! TODO: rewrite this function entirely
        new_flds = Fields((fields.Ex).shape[0])

        new_flds.Ex, new_flds.Ey, new_flds.Bx, new_flds.By =\
            calculate_Ex_Ey_Bx_By(
                self.grid_step_size, self.xi_step_size, self.trick,
                self.variant_A, const, fields, rho_beam_full, rho_beam_prev,
                currents_full, currents_prev
            )

        if self.variant_A:
            new_flds.Ex = 2 * new_flds.Ex - flds_prev.Ex
            new_flds.Ey = 2 * new_flds.Ey - flds_prev.Ey
            new_flds.Bx = 2 * new_flds.Bx - flds_prev.Bx
            new_flds.By = 2 * new_flds.By - flds_prev.By

        new_flds.Ez = calculate_Ez(self.grid_step_size, const, currents_full)
        new_flds.Bz = calculate_Bz(self.grid_step_size, const, currents_full)
        new_flds.Phi = calculate_Phi(const, currents_full)

        return new_flds, new_flds.average(flds_prev)
