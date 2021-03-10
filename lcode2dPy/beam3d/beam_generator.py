import scipy.stats as stats
import os
import pandas as pd
from pandas import DataFrame  as df
import numpy as np
from numpy import sqrt, pi

# BEAM PROFILES

def Gauss(med=0, sigma=1, vmin=-1, vmax=0):
    def gauss_maker(N):
        p1 = 0 if vmin is None else stats.norm.cdf(vmin)
        p2 = 1 if vmax is None else stats.norm.cdf(vmax)
        return stats.norm.ppf(np.linspace(p1, p2, N+2)[1:-1], med, sigma)
    gauss_maker.med = med
    gauss_maker.sigma = sigma
    gauss_maker.f0 = 1. / sqrt(2*pi) / sigma
    return gauss_maker

def rGauss(sigma=1, vmin=0, vmax=1):
    def rgauss_maker(N):
#         p1 = 0 if vmin is None else stats.weibull_min.cdf(vmin) # cdf doesn't work properly
#         p2 = 1 if vmax is None else stats.weibull_min.cdf(vmax)
        p1 = 0
        p2 = 1
        return sigma*np.sqrt(2.)*stats.weibull_min.ppf(np.linspace(p1, p2, N+2)[1:-1], 2)
    rgauss_maker.med = 0
    rgauss_maker.sigma = sigma
    return rgauss_maker

class Simulation():
    def __init__(self, geometry='circ', xi_step=0.01, x_step=0.01, y_step=0.01, xi_size=1, 
                 x_size=5, y_size=5, beam_partic_in_layer=200):
        self.geometry=geometry
        self.xi_step = xi_step
        self.x_step  = x_step
        self.y_step  = y_step
        self.xi_size = xi_size
        self.x_size  = x_size
        self.y_size  = y_size
        
def make_beam(self, xi_distr, pz_distr, Ipeak_kA,
              x_distr=None, y_distr=None, r_distr=None, px_distr=None, py_distr=None, ang_distr=None, 
              q_m=1.0, partic_in_layer=200,
              savehead=False, saveto=False, name='beamfile.bin'):
        if q_m == 1 and Ipeak_kA > 0:
            print('Warning: Electrons must have negative current.')
            return

        if xi_distr.med > 0:
            print('Warning: Beam center is in xi>0.')
            
        # xi_step = self.xi_step
    
        if saveto and 'beamfile.bin' in os.listdir(saveto):
            raise Exception('Another beamfile.bin is found. You may delete it using the following command: "!rm %s".' % os.path.join(saveto, name))
        I0 = 17.03331478052319 # kA
        q = 2.*Ipeak_kA/I0/partic_in_layer
        gamma = pz_distr.med 
        N = partic_in_layer / self.xi_step / xi_distr.f0
        N = int(round(N))
        xi = xi_distr(N)
        if savehead:
            xi = xi[xi >= -self.xi_size]
            N = len(xi)
        else:
            xi = xi[(xi >= -self.xi_size) & (xi <= 0)]
            N = len(xi)
        partic_in_mid_layer = np.sum((xi > xi_distr.med - self.xi_step/2) & (xi < xi_distr.med + self.xi_step/2))
        print('Number of particles:', N)
        print('Number of particles in the middle layer:', partic_in_mid_layer)
        xi = np.sort(xi)[::-1]

        if self.geometry == '3d':
            x = x_distr(N)
            if y_distr is not None:
                y = y_distr(N)
            else:
                y = x_distr(N)  
            np.random.shuffle(x)
            np.random.shuffle(y)
            pz = pz_distr(N)
            np.random.shuffle(pz)
            px = px_distr(N)
            if py_distr is not None:
                py = py_distr(N)
            else:
                py = px_distr(N)
            np.random.shuffle(px)
            np.random.shuffle(py)
            particles = np.array([xi, x, y, pz, px, py, q_m * np.ones(N), q * np.ones(N), np.arange(N)], dtype=float)
            stub_particle = np.array([[-100000., 0., 0., 0., 0., 0., 1.0, 0., 0.]])
            beam_data = np.vstack([particles.T, stub_particle])
            beam = df(beam_data, columns=['xi', 'x', 'y', 'pz', 'px', 'py', 'q_m', 'q', 'N'])
        head = beam[beam.eval('xi>0')]
        beam = beam[beam.eval('xi<=0'.format(-self.xi_size))]
        if saveto:
            beam.values.tofile(os.path.join(saveto, name))
        if savehead:
            head.values.tofile(os.path.join(saveto, 'head-' + name))
        return beam

def main():
    geometry = '3d'
    Simulation.make_beam = make_beam
    sim = Simulation(geometry=geometry)

    angspread = 1e-5
    m_proton = 958/0.51
    Ipeak_kA = 40/1000
    gamma = 426 * 5 * m_proton

    xi_distr=Gauss(vmin=-10, vmax=0)
    x_distr=Gauss(vmin=-7.5, vmax=7.5)
    px_distr=Gauss(sigma=gamma*angspread, vmin=None, vmax=None)
    pz_distr=Gauss(gamma, gamma*1e-4, vmin=None, vmax=None)

    beam = sim.make_beam(xi_distr=xi_distr, x_distr=x_distr, px_distr=px_distr,
                         pz_distr=pz_distr, Ipeak_kA=Ipeak_kA, q_m=1/m_proton,
                         partic_in_layer=1000)

    np.savez_compressed('beamfile',
                        xi = beam['xi'].to_numpy(),
                        x = beam['x'].to_numpy(),
                        y = beam['y'].to_numpy(),
                        p_x = beam['px'].to_numpy(),
                        p_y = beam['py'].to_numpy(),
                        p_z = beam['pz'].to_numpy(),
                        q_m = beam['q_m'].to_numpy(),
                        q_norm = beam['q'].to_numpy(),
                        id = beam['N'].to_numpy('int'))


if __name__ == '__main__':
    main()