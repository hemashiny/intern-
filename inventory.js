const express = require('express');
const router = express.Router();
const mlClient = require('../services/mlClient');

router.get('/plan', async (req, res) => {
  try {
    const { bucket, category } = req.query;
    const result = await mlClient.getInventoryPlan({ bucket, category });
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.get('/reorder-suggestions', async (req, res) => {
  try {
    const limit = req.query.limit ? Number(req.query.limit) : 20;
    const result = await mlClient.getReorderSuggestions(limit);
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

module.exports = router;
