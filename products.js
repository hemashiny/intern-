const express = require('express');
const router = express.Router();
const { query } = require('../config/db');

router.get('/', async (req, res) => {
  try {
    const rows = await query('SELECT * FROM products ORDER BY product_id');
    res.json({ success: true, count: rows.length, data: rows });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.get('/:id', async (req, res) => {
  try {
    const rows = await query('SELECT * FROM products WHERE product_id = ?', [req.params.id]);
    if (rows.length === 0) {
      return res.status(404).json({ success: false, error: 'Product not found' });
    }
    res.json({ success: true, data: rows[0] });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.post('/track/view', async (req, res) => {
  try {
    const { customer_id, product_id, view_duration_seconds = 0, session_id } = req.body;
    await query(
      `INSERT INTO product_views (customer_id, product_id, view_duration_seconds, session_id)
       VALUES (?, ?, ?, ?)`,
      [customer_id, product_id, view_duration_seconds, session_id]
    );
    res.json({ success: true });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

router.post('/track/click', async (req, res) => {
  try {
    const { customer_id, product_id, click_type = 'view_details', session_id } = req.body;
    await query(
      `INSERT INTO product_clicks (customer_id, product_id, click_type, session_id)
       VALUES (?, ?, ?, ?)`,
      [customer_id, product_id, click_type, session_id]
    );
    res.json({ success: true });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

module.exports = router;
