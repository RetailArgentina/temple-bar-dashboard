# Temple Bar Dashboard - Quick Start Guide

## What You Have

A professional executive dashboard for Temple Bar restaurants with real-time analytics across 21 locations.

## Opening the Dashboard (Right Now!)

1. Find the file: `/sessions/eloquent-determined-babbage/mnt/Claude_Cowork/super_dashboard_temple.html`
2. Double-click it or drag to your browser
3. Wait ~2 seconds for charts to load
4. You're done! Explore the dashboard

## What You See

### 5 Tabs
- **Resumen General** - Sales KPIs, trends, top establishments
- **Cervezas** - Beer styles, categories, revenue trends
- **Gin** - Gin products, liters consumed, top sellers
- **Feriado** - Holiday/special products performance
- **Productos** - Product mix breakdown by category

### Key Features
- **Date Picker** (top-left) - Select any date range
- **Establishment Filter** - Choose specific locations or all
- **Dark Mode** (moon icon) - Toggle for night viewing
- **Print Button** - Export to PDF via browser print
- **Auto-updating Tables** - Click "Aplicar" to refresh after filter changes

## Sample Analysis

Try these:
1. Select last 7 days → See daily trends
2. Filter to "SOHO" establishment → Compare against all
3. Go to Cervezas tab → See which beer style drives revenue
4. Toggle Dark Mode → Professional presentation mode
5. Click Print → Get PDF for reports

## Updating with New Data

When you have fresh BigQuery data:

```bash
cd /sessions/eloquent-determined-babbage/mnt/Claude_Cowork
python3 actualizar_dashboard.py --desde 2026-01-01 --hasta 2026-03-31
```

This will regenerate the HTML with new data.

## Key Numbers (Current Data)

- **Period**: Dec 15, 2025 - Mar 15, 2026
- **Total Records**: 14,345 data points
- **Locations**: 21 establishments
- **Categories Tracked**: Ventas, Mix, Cerveza, Gin, Feriado

## Formats

All monetary values shown in **Argentine Pesos (ARS)** with proper formatting (e.g., $1.234.567).

## No Installation Required

The dashboard works completely offline in your browser. No server, no installation, no dependencies!

## Keyboard Shortcuts

- `Ctrl+P` (or `Cmd+P` on Mac) - Print to PDF
- `F12` - Open browser developer tools (for debugging)
- `Ctrl+A` - Select all text (useful for copying tables)

## Common Tasks

### See top products by revenue
1. Go to "Productos" tab
2. Look at "Top 15 Productos - Revenue" chart
3. Hover for exact values

### Compare two periods
1. Set date range for Period 1
2. Note the KPI values
3. Change date range to Period 2
4. Compare the numbers

### Export to PowerPoint
1. Take screenshots of each tab
2. Print to PDF using "Print" button
3. Insert images into PowerPoint slides

### Find struggling location
1. Go to "Resumen General" tab
2. Scroll to "Top 10 Establecimientos" table
3. Look for red-highlighted rows (negative variance)
4. Click to see details

## Architecture

- **All-in-one HTML** - 1.4 MB file with embedded data
- **Client-side rendering** - No server calls
- **Real-time filtering** - <100ms response
- **Responsive design** - Works on mobile/tablet
- **Dark mode** - Saves preference to browser

## Data Sources

```
BigQuery Project: temple-bar-439715
Dataset: temple_bar

Tables:
- Ventas_Maestra (sales by estab/channel/shift)
- Mix_Maestro (product categories)
- Cerveza_Maestro (beer styles)
- Gin_Maestro (gin products)
- Feriado_Maestro (holiday specials)
```

## Next Steps

1. Open the dashboard now
2. Play with filters and tabs
3. Set up recurring refreshes (via cron job or scheduler)
4. Share the HTML file with stakeholders
5. Customize colors/layout if needed

## Support

For issues:
1. Check browser console (F12 → Console tab)
2. Try clearing browser cache
3. Ensure JavaScript is enabled
4. Try different browser (Chrome/Firefox/Safari)

---

**Created:** March 16, 2026
**Ready to use:** Yes, immediately!
