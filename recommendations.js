const express = require('express');
const router = express.Router();
const mlClient = require('../services/mlClient');

router.get('/:customerId', async (req, res) => {
  try {
    const limit = parseInt(req.query.limit, 10) || 10;
    const result = await mlClient.getRecommendations(req.params.customerId, limit);
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

module.exports = router;
