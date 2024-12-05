import * as tf from '@tensorflow/tfjs-node';
import { ImageProcessor } from './ImageProcessor';

export class ChartAIAnalyzer {
    private model: tf.LayersModel;
    private imageProcessor: ImageProcessor;

    constructor() {
        this.imageProcessor = new ImageProcessor();
        this.model = this.initializeModel();
    }

    private initializeModel(): tf.LayersModel {
        // Create a simple sequential model for demonstration
        const model = tf.sequential({
            layers: [
                tf.layers.conv2d({
                    inputShape: [224, 224, 3],
                    kernelSize: 3,
                    filters: 16,
                    activation: 'relu'
                }),
                tf.layers.maxPooling2d({ poolSize: 2 }),
                tf.layers.flatten(),
                tf.layers.dense({ units: 32, activation: 'relu' }),
                tf.layers.dense({ units: 3, activation: 'softmax' })
            ]
        });

        model.compile({
            optimizer: 'adam',
            loss: 'categoricalCrossentropy',
            metrics: ['accuracy']
        });

        return model;
    }

    async analyzeChart(imagePath: string): Promise<ChartAnalysis> {
        try {
            // Process the image using ImageProcessor
            const processedBuffer = await this.imageProcessor.preprocessImage(imagePath);

            // Convert Buffer to tensor
            const imageTensor = tf.node.decodeImage(processedBuffer, 3);
            const normalizedTensor = tf.div(imageTensor, 255.0);
            const batchedTensor = normalizedTensor.expandDims(0);

            // Make prediction
            const predictions = this.model.predict(batchedTensor) as tf.Tensor;
            const predictionArray = await predictions.data() as Float32Array;

            // Cleanup tensors
            imageTensor.dispose();
            normalizedTensor.dispose();
            batchedTensor.dispose();
            predictions.dispose();

            return {
                overallTrend: this.determineMarketTrend(predictionArray),
                confidenceLevels: Array.from(predictionArray),
                insights: this.generateInsights(predictionArray)
            };
        } catch (error) {
            console.error('Analysis failed:', error);
            throw new Error('Chart analysis failed');
        }
    }

    private determineMarketTrend(predictions: Float32Array): string {
        const maxIndex = Array.from(predictions).indexOf(Math.max(...predictions));
        const trends = ['Bullish', 'Bearish', 'Neutral'];
        return trends[maxIndex];
    }

    private generateInsights(predictions: Float32Array): string[] {
        const insights: string[] = [];
        const confidence = Math.max(...predictions);

        if (confidence > 0.7) {
            insights.push('High confidence prediction detected');
            insights.push(`Confidence level: ${(confidence * 100).toFixed(2)}%`);
        } else {
            insights.push('Moderate confidence prediction');
            insights.push(`Confidence level: ${(confidence * 100).toFixed(2)}%`);
        }

        return insights;
    }
}

interface ChartAnalysis {
    overallTrend: string;
    confidenceLevels: number[];
    insights: string[];
}