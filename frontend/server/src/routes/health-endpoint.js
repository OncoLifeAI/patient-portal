const express = require('express');
const router = express.Router();
const { api } = require('../utils/api.helpers');

router.get('/health', async (req, res) => {
  try {
    const data = await api.get('/health');
    res.status(200).json(data);
  } catch (error) {
    console.error('Health check error:', error);
    res.status(500).json({ 
      error: 'Health check failed',
      details: error.message 
    });
  }
});

module.exports = router; 