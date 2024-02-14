# Necessary imports
import astropy.io.fits as fits
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from scipy.signal import find_peaks
import astropy.units as u
import numpy as np
import pandas as pd
import sys
from os.path import exists
from datetime import date
from collections import defaultdict
from astropy.table import Table
from flux_calc import *
from emission_lines import *
import csv


# Pull spectra information
filename = sys.argv[1]
instrument = sys.argv[2]
grating = sys.argv[3]
star_name = sys.argv[4]
date = str(date.today())

# Fetch data
grating = grating.upper()
star_name = star_name.upper()
instrument = instrument.upper()
data = fits.getdata(filename)
w, f , e = data['WAVELENGTH'], data['FLUX'], data['ERROR']
mask = (w > 1160) # change if the spectra starts at a different wavelength

# Find peaks
if 'L' in grating:
    peaks, properties = find_peaks(f[mask], height = 0.7*sum(f[mask])/len(f[mask]), width = 0)
elif 'M' in grating:
    peaks, properties  = find_peaks(f[mask], height = 10*sum(f[mask])/len(f[mask]), prominence = 10*sum(f[mask])/len(f[mask]), width = 0, threshold = (1/10)*sum(f[mask])/len(f[mask]))
else:
    sys.exit("Invalid grating")

# Load Rest Lam data
data = pd.read_csv("DEM_goodlinelist.csv")
rest_lam_data = pd.DataFrame(data)

# Find the average width of the peaks
peak_width, peak_width_pixels, flux_range = peak_width_finder(grating, w[mask])

# Check if doppler file exists
doppler_filename = "./doppler/" + star_name + "_doppler.txt"
doppler_found = exists(doppler_filename)
if doppler_found:
    doppler_shift = np.loadtxt(doppler_filename)*(u.km/u.s)
else:
    doppler_shift = doppler_shift_calc(rest_lam_data, w[mask], f[mask], flux_range, star_name, doppler_filename)

# Check if noise file exists 
noise_filename = "./noise/" + star_name + "_noise.txt"
noise_found = exists(noise_filename)
if noise_found:
    noise_bool_list = np.loadtxt(noise_filename)

# Initializing necessary variables
flux = defaultdict(list)
count = 0 
iterations = 0
previous_obs = 0 *u.AA
prev_blended_bool = False
prev_left_bound = 0
emission_lines_list = []

# Find the emission lines
for wavelength in rest_lam_data["Wavelength"]:
    if(wavelength > 1160):  # change bounds if the spectra starts/ends at a different wavelength (and measure type)
        # obs_lam calculation from doppler
        rest_lam = wavelength * u.AA
        obs_lam = doppler_shift.to(u.AA,  equivalencies=u.doppler_optical(rest_lam))
        
        # Check for blended lines
        blended_line_bool = blended_line_check(previous_obs, obs_lam, iterations, flux_range)
        # Check if previous lam was also a blended line
        if blended_line_bool and prev_blended_bool:
            wavelength_mask = (w > prev_left_bound) & (w < (obs_lam.value + flux_range))
            prev_blended_bool = True
            emission_lines_list.pop()
        # If there is a blended line, and previous wasn't a blended line
        elif blended_line_bool:
            wavelength_mask = (w > (previous_obs.value - flux_range)) & (w < (obs_lam.value + flux_range))
            prev_blended_bool = True
            prev_left_bound = previous_obs.value - flux_range
            emission_lines_list.pop()
        # Not a blended line
        else:
            wavelength_mask = (w > (obs_lam.value - flux_range)) & (w < (obs_lam.value + flux_range))
            prev_blended_bool = False
        
        # Gaussian fit
        init_amp = np.max(f[wavelength_mask])
        init_params = [init_amp, np.mean(w[wavelength_mask]), np.std(w[wavelength_mask])]
        popt, _ = curve_fit(gaussian, w[wavelength_mask], f[wavelength_mask], p0=init_params, maxfev = 100000)
        amp, mu, sigma = popt
        x = np.linspace(np.min(w[wavelength_mask]), np.max(w[wavelength_mask]), len(w[wavelength_mask]))
        y = gaussian(x, amp, mu, sigma)
     
        # Append emission line
        ion = rest_lam_data['Ion'][count]
        emission_lines_list.append(emission_line(wavelength, ion, obs_lam, wavelength_mask, False, blended_line_bool, x, y))
    
        # Update variables
        previous_obs = obs_lam
        previous_index = len(flux[rest_lam_data['Ion'][count]]) - 1
        iterations+=1

    count+=1

if not noise_found:
    count = 0
    # Determine if the current emission line is noise
    for line in emission_lines_list:
        # Create basic plot
        fig = plt.figure(figsize=(14,7))
        ax = fig.add_subplot()
        fig.suptitle("Click 'y' if should be used for doppler calculation, 'n' if not", fontweight='bold')
        plt.title("Flux vs Wavelength for " + star_name, fontsize=18)
        plt.xlabel('Wavelength (Å)', fontsize=12)
        plt.ylabel('Flux (erg s$^{-1}$ cm$^{-2}$ Å$^{-1}$)', fontsize=12)
        trendline_patch = patches.Patch(color='pink', alpha=0.8, label='Continuum')
        rest_patch = patches.Patch(color='lightcoral', alpha=0.8, label='Rest Wavelength')
        obs_patch = patches.Patch(color='darkred', alpha=0.8, label='Observable Wavelength')
        gauss_patch = patches.Patch(color='mediumvioletred', alpha=0.8, label='Gaussian Fit')

        # Plot Gaussian fit
        ax.plot(line.gaussian_x, line.gaussian_y, '-', color='mediumvioletred', linewidth= 2.0)

        # Find Gaussian continuum
        continuum = []
        continuum_array = gaussian_trendline(w[line.flux_mask], line.gaussian_x, line.gaussian_y)

        # Plot emission lines
        ax.plot(w[line.flux_mask], f[line.flux_mask], linewidth = 1.2, alpha = 0.8)
        ax.plot(w[line.flux_mask], continuum_array, color="pink", alpha=0.7)
        plt.axvline(x = line.wavelength, color = 'lightcoral', label = 'Rest wavelength', linewidth= 1.8, ls = '--')
        plt.axvline(x = line.obs_lam.value, color = 'darkred', label = 'Observed wavelength', linewidth= 1.8, ls = '--')
        cid = fig.canvas.mpl_connect('key_press_event', lambda event: on_key(event, 'Noise Detection'))
        plt.legend(handles=[rest_patch, obs_patch, gauss_patch, trendline_patch])
        plt.show()
        
        # Calculate the flux and error
        w0,w1 = wavelength_edges(w[line.flux_mask])
        x_min = np.min(w[line.flux_mask])
        x_max = np.max(w[line.flux_mask])
        total_sumflux = gaussian_integral(amp, mu, sigma, x_min, x_max)
        sumerror = (np.sum(e[line.flux_mask]**2 * (w1-w0)**2))**0.5

        # Calculate the continuum
        for i in range(0, len(continuum_array)):
            continuum.append(continuum_array[i])
        continuum_sumflux = np.sum(continuum*(w1-w0))

        # Check if noise
        total_flux = total_sumflux - continuum_sumflux
        if noise_bool_list[count]:
            # Update emission line's noise bool
            line.noise_bool = noise_bool_list[count]
            # Update flux calculation
            total_flux = sumerror * (-3)
            sumerror = 0

        # Append to flux list
        flux[line.ion].append((line.wavelength, total_flux, sumerror, line.blended_bool))

        count+=1 
    
    # Save to file
    noise_array = np.array(noise_bool_list)
    np.savetxt(noise_filename, noise_array)

    # Printing
    for ion in flux:
        print(f"Ion: {ion} ")
        for data in flux[ion]:
            print(data)

# Plot the emission lines and trendlines
plt.figure(figsize=(14,10))
plt.plot(w[mask], f[mask], color="steelblue")
count = 0

for line in emission_lines_list:
    continuum_array = gaussian_trendline(w[line.flux_mask], line.gaussian_x, line.gaussian_y)

    if line.noise_bool:
        line_color = 'darkgreen'
    else:
        line_color = 'yellowgreen'

    plt.axvline(x=line.obs_lam.value, color= line_color, alpha=0.5)
    trendline, = plt.plot(w[line.flux_mask], continuum_array, color="darkorange", alpha=0.7)

    count+=1

# Create basic plot
plt.title("Flux vs Wavelength for " + star_name)
plt.xlabel('Wavelength (\AA)')
plt.ylabel('Flux (erg s$^{-1}$ cm$^{-2}$ \AA$^{-1}$)')
plt.ylabel('Flux (erg s$^{-1}$ cm$^{-2}$ \AA$^{-1}$)')

# Create plot legend
emission_patch = patches.Patch(color='yellowgreen', alpha=0.7, label='Emission Line')
noise_patch = patches.Patch(color='darkgreen', alpha=0.5, label='Noise')
trendline_patch = patches.Patch(color='darkorange', alpha=0.5, label='Flux Trendline')
plt.legend(handles=[emission_patch, noise_patch, trendline_patch])
plt.show()

# Exit if flux has already been calculated <- NOTE: to adjust flux calculations, DELETE all flux calculations and noise bool
if noise_found:
    sys.exit('Flux already added to ECSV and FITS file, to recalculate, delete noise file and restart')

# Create a fits file
data_array = []
fits_filename = "./flux/" + star_name.lower() + ".fits"
ecsv_filename = "./flux/" + star_name.lower() + ".ecsv"

for ion in flux:
    for data in flux[ion]:
        data_array.append({"Ion": ion, "Wavelength": data[0], "Flux": data[1], "Error": data[2], "Blended line": data[3]})

t = Table(rows=data_array)
t.write(fits_filename, overwrite=True) 
t.write(ecsv_filename, overwrite = True) # does not have a header

# Update header
with fits.open(fits_filename, mode='update') as hdul:
    hdr = hdul[0].header
    hdr.set('DATE', date, 'date flux was calculated')
    hdr.set('FILENAME', filename, 'name of the fits file used to calculate the flux')
    hdr.set('FILETYPE', "SCI", 'file type of fits file')
    hdr.set('TELESCP', "HST", 'telescope used to measure flux')
    hdr.set('INSTRMNT', instrument, 'active instrument to measure flux')
    hdr.set('GRATING', grating, 'grating used to measure flux')
    hdr.set('TARGNAME', star_name, 'name of star used in measurement')
    hdr.set('DOPPLER', str(doppler_shift.value) + " km/s", 'doppler shift used to measure flux')
    hdr.set('WIDTH', "+/- " + str(peak_width) + " Angstroms", 'peak_width used to measure flux')
    hdr.set('RANGE', "+/- " + str(flux_range) + " Angstroms", 'flux range used to measure flux')
    hdr.set('WIDTHPXL', peak_width_pixels, 'peak_width in pixels used to measure flux')
    hdr.set('UPRLIMIT', "3*error", 'upper limit used to determine noise')
    hdul.flush() 