import * as sharp from 'sharp';
import * as tf from '@tensorflow/tfjs-node';

export class ImageProcessor {
    async preprocessImage(imagePath: string): Promise<tf.Tensor4D> {
        try {
            const imageBuffer = await sharp(imagePath)
                .resize(224, 224)
                .normalize()
                .toBuffer();

            return tf.node.decodeImage(imageBuffer, 3)
                .expandDims(0)
                .toFloat()
                .div(255.0) as tf.Tensor4D;
        } catch (error) {
            console.error('Image Preprocessing Error:', error);
            throw error;
        }
    }
}