const express = require('express');
const router = express.Router();
const mlClient = require('../services/mlClient');

router.get('/', async (req, res) => {
  try {
    const result = await mlClient.getBusinessInsights();
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.get('/gold-price', async (req, res) => {
  try {
    const refresh = req.query.refresh === 'true';
    const result = await mlClient.getGoldPrice(refresh);
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.get('/festivals', async (req, res) => {
  try {
    const days = req.query.days ? Number(req.query.days) : 90;
    const result = await mlClient.getFestivals(days, req.query.country);
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.get('/competitors', async (req, res) => {
  try {
    const limit = req.query.limit ? Number(req.query.limit) : 20;
    const result = await mlClient.getCompetitorPrices(req.query.category, limit);
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.get('/trending', async (req, res) => {
  try {
    const result = await mlClient.getTrendingCategories();
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.get('/silver-price', async (req, res) => {
  try {
    const refresh = req.query.refresh === 'true';
    const result = await mlClient.getSilverPrice(refresh);
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.get('/fx-rates', async (req, res) => {
  try {
    const refresh = req.query.refresh === 'true';
    const result = await mlClient.getFxRates(refresh);
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.get('/ibja-rates', async (req, res) => {
  try {
    const refresh = req.query.refresh === 'true';
    const result = await mlClient.getIbjaRates(refresh);
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.get('/economic-indicators', async (req, res) => {
  try {
    const refresh = req.query.refresh === 'true';
    const result = await mlClient.getEconomicIndicators(refresh);
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.get('/market-pulse', async (req, res) => {
  try {
    const refresh = req.query.refresh === 'true';
    const result = await mlClient.getMarketPulse(refresh);
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

module.exports = router;
