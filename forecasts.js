const express = require('express');
const router = express.Router();
const mlClient = require('../services/mlClient');

router.get('/', async (req, res) => {
  try {
    const { horizon, scope, id, persist } = req.query;
    const result = await mlClient.getForecasts({
      horizon, scope, id, persist: persist === 'true',
    });
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.get('/summary', async (req, res) => {
  try {
    const result = await mlClient.getForecastSummary();
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

module.exports = router;
