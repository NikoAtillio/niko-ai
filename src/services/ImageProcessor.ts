import sharp from 'sharp';

export class ImageProcessor {
    async preprocessImage(imagePath: string): Promise<Buffer> {
        try {
            const imageBuffer = await sharp(imagePath)
                .resize(224, 224)
                .normalize()
                .toBuffer();

            return imageBuffer;
        } catch (error) {
            console.error('Error processing image:', error);
            throw new Error('Image processing failed');
        }
    }
}