const express = require('express');
const cors = require('cors');
const bodyParser = require('body-parser');
const cron = require('node-cron');
require('dotenv').config();

const { testConnection } = require('./config/db');
const mlClient = require('./services/mlClient');

const predictionsRouter = require('./routes/predictions');
const recommendationsRouter = require('./routes/recommendations');
const dashboardRouter = require('./routes/dashboard');
const productsRouter = require('./routes/products');
const insightsRouter = require('./routes/insights');
const adminRouter = require('./routes/admin');
const forecastsRouter = require('./routes/forecasts');
const offersRouter = require('./routes/offers');
const inventoryRouter = require('./routes/inventory');
const alertsRouter = require('./routes/alerts');

const app = express();
const PORT = process.env.PORT || 5000;

app.use(cors({ origin: process.env.CORS_ORIGIN || '*' }));
app.use(bodyParser.json({ limit: '10mb' }));
app.use(bodyParser.urlencoded({ extended: true }));

app.use((req, res, next) => {
  console.log(`[${new Date().toISOString()}] ${req.method} ${req.path}`);
  next();
});

app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'jewelry-sales-predictor-api' });
});

app.use('/api/predictions', predictionsRouter);
app.use('/api/recommendations', recommendationsRouter);
app.use('/api/dashboard', dashboardRouter);
app.use('/api/products', productsRouter);
app.use('/api/business-insights', insightsRouter);
app.use('/api/admin', adminRouter);
app.use('/api/forecasts', forecastsRouter);
app.use('/api/offers', offersRouter);
app.use('/api/inventory', inventoryRouter);
app.use('/api/alerts', alertsRouter);

app.use((err, req, res, next) => {
  console.error('Unhandled error:', err);
  res.status(500).json({ success: false, error: err.message });
});

cron.schedule('0 */6 * * *', async () => {
  console.log('Running scheduled prediction refresh...');
  try {
    const result = await mlClient.getPredictions(true);
    console.log(`Refreshed ${result.count || 0} predictions`);
  } catch (err) {
    console.error('Scheduled prediction failed:', err.message);
  }
});

// Hourly: refresh gold/silver/FX snapshots so api_snapshots and
// metal_price_history accumulate time-series data for the dashboard.
cron.schedule('0 * * * *', async () => {
  console.log('Running hourly market-data snapshot...');
  try {
    const result = await mlClient.adminRefresh();
    console.log('Hourly snapshot OK:', JSON.stringify(result.data || {}));
  } catch (err) {
    console.error('Hourly snapshot failed:', err.message);
  }
});

// Daily 02:15: persist daily/weekly/monthly overall forecasts so the
// sales_forecasts table accumulates a history we can chart later.
cron.schedule('15 2 * * *', async () => {
  console.log('Running daily forecast persistence...');
  for (const horizon of ['daily', 'weekly', 'monthly']) {
    try {
      await mlClient.getForecasts({ horizon, scope: 'overall', persist: true });
    } catch (err) {
      console.error(`Forecast persist (${horizon}) failed:`, err.message);
    }
  }
});

// Daily 09:00 local: explicit gold-rate refresh from API + crawler
// (gold-api.com, goldprice.org, goodreturns.in scraper, IBJA bullion).
// Hourly snapshot above already covers this; the daily job is the
// authoritative "opening fix" pull used for the day's reporting.
cron.schedule('0 9 * * *', async () => {
  console.log('Running daily gold-rate refresh (API + crawler)...');
  try {
    const gold = await mlClient.getGoldPrice(true);
    const ibja = await mlClient.getIbjaRates(true);
    console.log(
      'Daily gold OK — goodreturns 24K:', (gold.data || {}).price_inr_per_gram_24k,
      '· IBJA 999:', (ibja.data || {}).gold_999_24k_inr_per_g,
    );
  } catch (err) {
    console.error('Daily gold refresh failed:', err.message);
  }
});

// Every 30 minutes: generate + persist alerts so the admin dashboard
// reflects the latest market and inventory situation.
cron.schedule('*/30 * * * *', async () => {
  console.log('Running alerts generation...');
  try {
    const result = await mlClient.generateAlerts();
    console.log(`Alerts generated: ${result.data && result.data.total || 0}`);
  } catch (err) {
    console.error('Alerts generation failed:', err.message);
  }
});

async function start() {
  const dbOk = await testConnection();
  if (!dbOk) {
    console.warn('Warning: database connection failed. Endpoints depending on DB will error.');
  }
  app.listen(PORT, () => {
    console.log(`Backend API listening on port ${PORT}`);
  });
}

start();
