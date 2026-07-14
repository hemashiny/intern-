const express = require('express');
const router = express.Router();
const mlClient = require('../services/mlClient');

router.post('/refresh', async (req, res) => {
  try {
    const result = await mlClient.adminRefresh();
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.get('/refresh', async (req, res) => {
  try {
    const result = await mlClient.adminRefresh();
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.get('/health', async (req, res) => {
  try {
    const result = await mlClient.getAdminHealth();
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.get('/dashboard', async (req, res) => {
  try {
    const result = await mlClient.getAdminDashboard();
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

module.exports = router;
