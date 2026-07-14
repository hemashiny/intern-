const express = require('express');
const router = express.Router();
const mlClient = require('../services/mlClient');

router.get('/', async (req, res) => {
  try {
    const { type, limit } = req.query;
    const result = await mlClient.getOffers({
      type,
      limit: limit ? Number(limit) : undefined,
    });
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

module.exports = router;
