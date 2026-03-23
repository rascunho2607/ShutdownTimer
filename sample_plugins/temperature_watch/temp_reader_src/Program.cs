/*
 * temp_reader — CPU Temperature Reader for Temperature Watch plugin
 *
 * Reads the highest CPU temperature available on Windows using:
 *   1. MSAcpi_ThermalZoneTemperature (root\wmi) — works on most modern PCs
 *   2. Win32_PerfFormattedData_Counters_ThermalZoneInformation (root\cimv2)
 *
 * Outputs a single float (e.g. "57.3") to stdout, or "-1" on failure.
 * Designed to be called as a subprocess by the Python plugin.
 *
 * Build:
 *   dotnet publish -c Release -r win-x64 --self-contained true
 *       -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true
 *       -o ../
 */

using System;
using System.Management;

class Program
{
    static int Main()
    {
        try
        {
            // ── Method 1: MSAcpi_ThermalZoneTemperature (root\wmi) ─────────
            double best = TryAcpiThermalZone();
            if (best > 0)
            {
                Console.WriteLine(best.ToString("F1",
                    System.Globalization.CultureInfo.InvariantCulture));
                return 0;
            }

            // ── Method 2: Win32 Thermal Zone counters (root\cimv2) ─────────
            best = TryWin32ThermalZone();
            if (best > 0)
            {
                Console.WriteLine(best.ToString("F1",
                    System.Globalization.CultureInfo.InvariantCulture));
                return 0;
            }
        }
        catch
        {
            // fall through
        }

        Console.WriteLine("-1");
        return 1;
    }

    // ── MSAcpi_ThermalZoneTemperature (root\wmi) ───────────────────────────
    static double TryAcpiThermalZone()
    {
        double maxTemp = -1;
        try
        {
            using var searcher = new ManagementObjectSearcher(
                @"root\wmi",
                "SELECT CurrentTemperature FROM MSAcpi_ThermalZoneTemperature");

            foreach (ManagementObject obj in searcher.Get())
            {
                // Temperature is in tenths of Kelvin
                double kelvinTenths = Convert.ToDouble(obj["CurrentTemperature"]);
                double celsius = (kelvinTenths / 10.0) - 273.15;
                if (celsius > 0 && celsius < 200 && celsius > maxTemp)
                    maxTemp = celsius;
            }
        }
        catch { }
        return maxTemp;
    }

    // ── Win32_PerfFormattedData_Counters_ThermalZoneInformation ───────────
    static double TryWin32ThermalZone()
    {
        double maxTemp = -1;
        try
        {
            using var searcher = new ManagementObjectSearcher(
                @"root\cimv2",
                "SELECT Temperature FROM Win32_PerfFormattedData_Counters_ThermalZoneInformation");

            foreach (ManagementObject obj in searcher.Get())
            {
                // This counter already reports Kelvin (not tenths)
                double kelvin = Convert.ToDouble(obj["Temperature"]);
                double celsius = kelvin - 273.15;
                if (celsius > 0 && celsius < 200 && celsius > maxTemp)
                    maxTemp = celsius;
            }
        }
        catch { }
        return maxTemp;
    }
}
