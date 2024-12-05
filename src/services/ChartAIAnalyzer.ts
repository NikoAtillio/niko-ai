import * as tf from '@tensorflow/tfjs-node';
import * as sharp from 'sharp';
import { ImageProcessor } from './ImageProcessor';

export class ChartAIAnalyzer {
    private model: tf.LayersModel | null = null;
    private imageProcessor: ImageProcessor;

    constructor() {
        this.imageProcessor = new ImageProcessor();
        this.initializeModel();
    }

    private async initializeModel(): Promise<void> {
        // Simple model for MVP
        this.model = tf.sequential({
            layers: [
                tf.layers.conv2d({
                    inputShape: [224, 224, 3],
                    kernelSize: 3,
                    filters: 16,
                    activation: 'relu'
                }),
                tf.layers.maxPooling2d({ poolSize: [2, 2] }),
                tf.layers.flatten(),
                tf.layers.dense({ units: 32, activation: 'relu' }),
                tf.layers.dense({ units: 2, activation: 'softmax' })
            ]
        });

        this.model.compile({
            optimizer: 'adam',
            loss: 'categoricalCrossentropy',
            metrics: ['accuracy']
        });
    }

    async analyzeChart(imagePath: string): Promise<ChartAnalysis> {
        try {
            // Use ImageProcessor to handle image preprocessing
            const processedImage = await this.imageProcessor.preprocessImage(imagePath);

            if (!this.model) {
                throw new Error('Model not initialized');
            }

            const predictions = this.model.predict(processedImage) as tf.Tensor;
            return this.interpretResults(predictions);
        } catch (error) {
            console.error('Analysis failed:', error);
            throw new Error('Chart analysis error');
        }
    }

    private interpretResults(predictions: tf.Tensor): ChartAnalysis {
        const predictionData = predictions.dataSync();
        predictions.dispose(); // Clean up tensor

        return {
            overallTrend: predictionData[0] > 0.5 ? 'Bullish' : 'Bearish',
            confidenceLevels: Array.from(predictionData),
            insights: this.generateInsights(Array.from(predictionData))
        };
    }

    private generateInsights(predictions: number[]): string[] {
        const insights: string[] = [];
        const confidence = predictions[0];

        if (confidence > 0.8) {
            insights.push('Strong signal detected');
        } else if (confidence > 0.6) {
            insights.push('Moderate signal detected');
        } else {
            insights.push('Weak signal detected');
        }

        return insights;
    }
}

export interface ChartAnalysis {
    overallTrend: string;
    confidenceLevels: number[];
    insights: string[];
}