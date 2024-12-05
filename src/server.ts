// src/server.ts
import express from 'express';
import multer from 'multer';
import path from 'path';
import * as tf from '@tensorflow/tfjs-node';
import { ChartAIAnalyzer } from './services/ChartAIAnalyzer';
import sharp from 'sharp';

const app = express();
const port = process.env.PORT || 3000;

// Configure multer for memory storage
const upload = multer({
    storage: multer.memoryStorage(),
    limits: {
        fileSize: 5 * 1024 * 1024 // 5MB limit
    }
});

// Initialize ChartAIAnalyzer
const chartAnalyzer = new ChartAIAnalyzer();

// Serve static files
app.use(express.static('public'));

// Add logging middleware
app.use((req, res, next) => {
    console.log(`${req.method} ${req.path}`);
    next();
});

app.post('/analyze', upload.single('chart'), async (req, res) => {
    try {
        if (!req.file) {
            throw new Error('No file uploaded');
        }

        console.log('File received:', req.file.originalname);

        // Process image with sharp
        const processedImageBuffer = await sharp(req.file.buffer)
            .resize(224, 224)
            .toBuffer();

        // Convert to tensor
        const tensor = tf.node.decodeImage(processedImageBuffer, 3);

        // Analyze the chart
        const analysis = await chartAnalyzer.analyzeChart(tensor as tf.Tensor3D);

        // Clean up tensor
        tensor.dispose();

        console.log('Analysis completed:', analysis);
        res.json(analysis);
    } catch (error) {
        console.error('Error processing image:', error);
        res.status(500).json({
            success: false,
            error: error instanceof Error ? error.message : 'Unknown error occurred'
        });
    }
});

app.get('/test', (_req, res) => {
    res.json({ message: 'API is working' });
});

app.listen(port, () => {
    console.log(`Server running at http://localhost:${port}`);
});