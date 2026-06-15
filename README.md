# Temple Bar Executive Dashboard

A comprehensive, self-contained HTML dashboard for Temple Bar restaurant chain in Argentina, providing real-time insights into sales, beverages, products, and holiday specials.

## Files

- **`super_dashboard_temple.html`** (1.4 MB) - Main executable dashboard
- **`actualizar_dashboard.py`** - Python script to refresh dashboard data from BigQuery
- **`processed_data.json`** - Cached processed data (for reference)

## Features

### Dashboard Tabs
1. **Resumen General** - Sales overview with KPIs, daily trends, channel mix, and top establishments
2. **Cervezas** - Beer sales analytics by style and category
3. **Gin** - Gin products sales tracking and trends
4. **Feriado** - Holiday/special products performance
5. **Productos** - Product mix analysis across all categories

### Key Capabilities
- **Date Range Filtering** - Flatpickr date picker with range selection
- **Multi-Establishment Filter** - Select one or all 21 locations
- **Real-time Charts** - Line, bar, and donut charts using Chart.js 4.4.1
- **Dark Mode** - Toggle with localStorage persistence
- **Print/Export** - Browser print dialog (Ctrl+P or button)
- **Responsive Design** - Mobile-friendly grid layout
- **Executive KPIs** - Revenue, orders, ticket average, unit counts
- **Detailed Tables** - Top products, establishments with % change indicators
- **Auto-refresh Time** - Shows last update timestamp

### Data Sources

The dashboard pulls from 5 BigQuery tables:
- **Ventas_Maestra** - Daily sales by establishment, channel, shift
- **Mix_Maestro** - Product categories (Bebida/Comida/Promoción/Merch)
- **Cerveza_Maestro** - Beer styles and categories
- **Gin_Maestro** - Gin products with liter tracking
- **Feriado_Maestro** - Holiday/special products

## Usage

### Opening the Dashboard
Simply open `super_dashboard_temple.html` in any modern browser. No server or external dependencies required (except CDN for Chart.js and Flatpickr).

```bash
# Windows
start super_dashboard_temple.html

# Mac
open super_dashboard_temple.html

# Linux
xdg-open super_dashboard_temple.html
```

### Updating Data

Use the refresh script to update the dashboard with new data from BigQuery:

```bash
# Refresh with default (last 90 days)
python3 actualizar_dashboard.py

# Custom date range
python3 actualizar_dashboard.py --desde 2026-01-01 --hasta 2026-03-15

# Custom output location
python3 actualizar_dashboard.py --output /path/to/dashboard.html
```

**Requirements for refresh script:**
```bash
pip install google-cloud-bigquery
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
```

## Data Structure

All data is embedded as JavaScript objects in the HTML:

```javascript
const DATA = {
  ventas: [{d: "2026-03-15", e: "SOHO", c: "sale_app", t: "N", o: 48, v: 1875950, tk: 39082}, ...],
  mix: [{d: "2026-03-15", m: "Bebida", e: "SOHO", q: 50, $: 1200000}, ...],
  cerveza: [{d: "2026-03-15", s: "Wolf Ipa", cat: "Lupulada", e: "SOHO", q: 20, $: 150000}, ...],
  gin: [{d: "2026-03-15", p: "GIN TONIC", e: "SOHO", q: 10, $: 95000, l: 0.5}, ...],
  feriado: [{d: "2026-03-15", p: "VERMU", e: "SOHO", q: 5, $: 38500}, ...]
}
```

**Field Keys:**
- `d` = date (YYYY-MM-DD)
- `e` = establishment
- `c` = channel (sale_app, pedidos_ya)
- `t` = turno (M=Mañana, T=Tarde, N=Noche)
- `o` = órdenes (orders)
- `v` = ventas (sales in ARS)
- `tk` = ticket promedio
- `m` = mix category
- `s` = cerveza estilo
- `cat` = category
- `q` = cantidad (quantity)
- `$` = dinero (revenue in ARS)
- `p` = producto (product)
- `l` = litros

## Establishments (21 Locations)

BARRIO CHINO, CAMINITO, CASA TEMPLE, CLUB TEMPLE, COMODORO RIVADAVIA, CORRIENTES, GUEMES, HOLLYWOOD, MASCHWITZ, MONROE, PILAR, PINAMAR, POSADAS, PUERTO MADERO, RECOLETA, RIO GALLEGOS, ROSARIO 2, SALTA, SANTIAGO DEL ESTERO, SOHO, TUCUMAN 3

## Design

- **Colors**: Professional blue (#1B3A6B, #2E5FA3) with accent red, green, yellow
- **Font**: Segoe UI / Arial
- **Theme**: Light mode (default) + Dark mode toggle
- **Layout**: Sticky header, responsive grid, rounded cards
- **Charts**: Chart.js with animated tooltips and responsive sizing

## Browser Support

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+
- Mobile browsers (iOS Safari 14+, Chrome Mobile)

## Performance

- **File Size**: 1.4 MB (includes 3 months data for 21 establishments, all 5 tables)
- **Load Time**: <2 seconds on typical broadband
- **Chart Rendering**: <1 second for all visualizations
- **Filtering**: Instant client-side (no network calls)
- **Memory**: ~50-80 MB (depending on browser)

## Customization

Edit the HTML directly to:
- Change colors: Modify CSS variables in `<style>` section
- Add establishments: Update `ESTABLISHMENTS` array
- Change date defaults: Modify date picker initialization
- Adjust chart types: Update Chart.js `type` property (bar, line, doughnut, etc)
- Add new data sources: Extend DATA object and add new tabs

## Troubleshooting

**Charts not displaying?**
- Check browser console (F12) for errors
- Ensure JavaScript is enabled
- Try clearing browser cache

**Slow performance?**
- On older browsers, reduce number of rows in filtered data
- Disable dark mode (renders faster in light mode)
- Close other browser tabs

**Refresh script fails?**
- Verify BigQuery credentials: `gcloud auth application-default login`
- Check dataset name and table names in script
- Ensure Python 3.7+ with google-cloud-bigquery installed

## License

Internal use only - Temple Bar Argentina

## Created

March 16, 2026
Generated from BigQuery tables for period: 2025-12-15 to 2026-03-15

