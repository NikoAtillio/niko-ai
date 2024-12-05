import express, { Request, Response } from 'express';
import multer from 'multer';
import path from 'path';
import { ChartAIAnalyzer } from './services/ChartAIAnalyzer';

const app = express();
const upload = multer({ dest: 'uploads/' });
const chartAnalyzer = new ChartAIAnalyzer();

app.use(express.static('public'));

app.post('/analyze-chart', upload.single('chart'), async (req: Request, res: Response): Promise<void> => {
    try {
        if (!req.file) {
            res.status(400).json({ error: 'No file uploaded' });
            return;
        }

        const analysis = await chartAnalyzer.analyzeChart(req.file.path);
        res.json(analysis);
    } catch (error) {
        console.error('Analysis error:', error);
        res.status(500).json({ error: 'Analysis failed' });
    }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`Server running on port ${PORT}`);
});