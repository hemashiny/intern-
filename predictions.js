const express = require('express');
const router = express.Router();
const mlClient = require('../services/mlClient');
const { query } = require('../config/db');

router.get('/', async (req, res) => {
  try {
    const persist = req.query.persist === 'true';
    const result = await mlClient.getPredictions(persist);
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.get('/latest', async (req, res) => {
  try {
    const rows = await query(`
      SELECT pr.*, p.item_no, p.product_name, p.category, p.price
      FROM prediction_results pr
      JOIN products p ON pr.product_id = p.product_id
      INNER JOIN (
        SELECT product_id, MAX(created_at) AS latest
        FROM prediction_results GROUP BY product_id
      ) l ON pr.product_id = l.product_id AND pr.created_at = l.latest
      ORDER BY pr.prediction_percentage DESC
    `);
    res.json({ success: true, count: rows.length, data: rows });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.get('/:productId', async (req, res) => {
  try {
    const result = await mlClient.getPredictionForProduct(req.params.productId);
    res.json(result);
  } catch (err) {
    const status = err.response?.status || 500;
    res.status(status).json({ success: false, error: err.message });
  }
});

router.get('/history/:productId', async (req, res) => {
  try {
    const rows = await query(
      `SELECT * FROM prediction_results
       WHERE product_id = ?
       ORDER BY created_at DESC LIMIT 30`,
      [req.params.productId]
    );
    res.json({ success: true, count: rows.length, data: rows });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

module.exports = router;
