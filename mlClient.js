const axios = require('axios');

const ML_BASE_URL = process.env.ML_SERVICE_URL || 'http://localhost:5001';

const mlClient = axios.create({
  baseURL: ML_BASE_URL,
  timeout: 30000,
});

async function getPredictions(persist = false) {
  const { data } = await mlClient.get('/api/predictions', { params: { persist } });
  return data;
}

async function getPredictionForProduct(productId) {
  const { data } = await mlClient.get(`/api/predictions/${productId}`);
  return data;
}

async function getRecommendations(customerId, limit = 10) {
  const { data } = await mlClient.get(`/api/recommendations/${customerId}`, {
    params: { limit },
  });
  return data;
}

async function getKpis() {
  const { data } = await mlClient.get('/api/dashboard/kpis');
  return data;
}

async function getBusinessInsights() {
  const { data } = await mlClient.get('/api/business-insights');
  return data;
}

async function getGoldPrice(refresh = false) {
  const { data } = await mlClient.get('/api/integrations/gold-price', { params: { refresh } });
  return data;
}

async function getFestivals(days = 90, country) {
  const { data } = await mlClient.get('/api/integrations/festivals', { params: { days, country } });
  return data;
}

async function getCompetitorPrices(category, limit = 20) {
  const { data } = await mlClient.get('/api/integrations/competitors', { params: { category, limit } });
  return data;
}

async function getTrendingCategories() {
  const { data } = await mlClient.get('/api/integrations/trends');
  return data;
}

async function getSilverPrice(refresh = false) {
  const { data } = await mlClient.get('/api/integrations/silver-price', { params: { refresh } });
  return data;
}

async function getFxRates(refresh = false) {
  const { data } = await mlClient.get('/api/integrations/fx-rates', { params: { refresh } });
  return data;
}

async function getIbjaRates(refresh = false) {
  const { data } = await mlClient.get('/api/integrations/ibja-rates', { params: { refresh } });
  return data;
}

async function getEconomicIndicators(refresh = false) {
  const { data } = await mlClient.get('/api/integrations/economic-indicators', { params: { refresh } });
  return data;
}

async function getMarketPulse(refresh = false) {
  const { data } = await mlClient.get('/api/integrations/market-pulse', { params: { refresh } });
  return data;
}

async function adminRefresh() {
  const { data } = await mlClient.post('/api/admin/refresh');
  return data;
}

async function getAdminHealth() {
  const { data } = await mlClient.get('/api/admin/health');
  return data;
}

async function getForecasts({ horizon, scope, id, persist } = {}) {
  const { data } = await mlClient.get('/api/forecasts', {
    params: { horizon, scope, id, persist },
  });
  return data;
}

async function getForecastSummary() {
  const { data } = await mlClient.get('/api/forecasts/summary');
  return data;
}

async function getOffers({ type, limit } = {}) {
  const { data } = await mlClient.get('/api/offers', { params: { type, limit } });
  return data;
}

async function getInventoryPlan({ bucket, category } = {}) {
  const { data } = await mlClient.get('/api/inventory-plan', {
    params: { bucket, category },
  });
  return data;
}

async function getReorderSuggestions(limit = 20) {
  const { data } = await mlClient.get('/api/inventory/reorder-suggestions', {
    params: { limit },
  });
  return data;
}

async function getAlerts({ persist, severity, type, includeHistory, limit } = {}) {
  const { data } = await mlClient.get('/api/alerts', {
    params: {
      persist, severity, type,
      include_history: includeHistory,
      limit,
    },
  });
  return data;
}

async function generateAlerts() {
  const { data } = await mlClient.post('/api/alerts/generate');
  return data;
}

async function acknowledgeAlert(alertId) {
  const { data } = await mlClient.post(`/api/alerts/${alertId}/ack`);
  return data;
}

async function getAdminDashboard() {
  const { data } = await mlClient.get('/api/admin/dashboard');
  return data;
}

module.exports = {
  getPredictions,
  getPredictionForProduct,
  getRecommendations,
  getKpis,
  getBusinessInsights,
  getGoldPrice,
  getSilverPrice,
  getFxRates,
  getIbjaRates,
  getEconomicIndicators,
  getMarketPulse,
  getFestivals,
  getCompetitorPrices,
  getTrendingCategories,
  adminRefresh,
  getAdminHealth,
  getForecasts,
  getForecastSummary,
  getOffers,
  getInventoryPlan,
  getReorderSuggestions,
  getAlerts,
  generateAlerts,
  acknowledgeAlert,
  getAdminDashboard,
};
