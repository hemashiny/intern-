const express = require('express');
const router = express.Router();
const mlClient = require('../services/mlClient');

router.get('/', async (req, res) => {
  try {
    const result = await mlClient.getAlerts({
      persist: req.query.persist === 'true',
      severity: req.query.severity,
      type: req.query.type,
      includeHistory: req.query.include_history === 'true',
      limit: req.query.limit ? Number(req.query.limit) : undefined,
    });
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.post('/generate', async (req, res) => {
  try {
    const result = await mlClient.generateAlerts();
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.post('/:id/ack', async (req, res) => {
  try {
    const result = await mlClient.acknowledgeAlert(req.params.id);
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

module.exports = router;
