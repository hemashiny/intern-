const express = require('express');
const router = express.Router();
const mlClient = require('../services/mlClient');
const { query } = require('../config/db');

router.get('/kpis', async (req, res) => {
  try {
    const result = await mlClient.getKpis();
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.get('/summary', async (req, res) => {
  try {
    const [totals] = await query(`
      SELECT
        (SELECT COUNT(*) FROM products) AS total_products,
        (SELECT COUNT(*) FROM customers) AS total_customers,
        (SELECT COALESCE(SUM(sale_amount), 0) FROM sales_history) AS total_revenue,
        (SELECT COUNT(*) FROM sales_history) AS total_sales
    `);
    res.json({ success: true, data: totals });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.get('/demand-breakdown', async (req, res) => {
  try {
    const rows = await query(`
      SELECT demand_status, COUNT(*) AS count
      FROM (
        SELECT pr.product_id, pr.demand_status
        FROM prediction_results pr
        INNER JOIN (
          SELECT product_id, MAX(created_at) AS latest
          FROM prediction_results GROUP BY product_id
        ) l ON pr.product_id = l.product_id AND pr.created_at = l.latest
      ) latest_preds
      GROUP BY demand_status
    `);
    res.json({ success: true, data: rows });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

module.exports = router;
