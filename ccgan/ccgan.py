from __future__ import print_function, division

from keras.datasets import mnist
from keras_contrib.layers.normalization import InstanceNormalization
from keras.layers import Input, Dense, Reshape, Flatten, Dropout, multiply, GaussianNoise
from keras.layers import BatchNormalization, Activation, Embedding, ZeroPadding2D
from keras.layers import Concatenate
from keras.layers.advanced_activations import LeakyReLU
from keras.layers.convolutional import UpSampling2D, Conv2D
from keras.models import Sequential, Model
from keras.optimizers import Adam
from keras import losses
from keras.utils import to_categorical
import keras.backend as K
import scipy

import matplotlib.pyplot as plt

import numpy as np

class CCGAN():
    def __init__(self):
        self.img_rows = 32
        self.img_cols = 32
        self.mask_height = 10
        self.mask_width = 10
        self.channels = 1
        self.num_classes = 10
        self.img_shape = (self.img_rows, self.img_cols, self.channels)

        optimizer = Adam(0.0002, 0.5)

        # Build and compile the discriminator
        self.discriminator = self.build_discriminator()
        self.discriminator.compile(loss=['mse', 'categorical_crossentropy'],
            loss_weights=[0.5, 0.5],
            optimizer=optimizer,
            metrics=['accuracy'])

        # Build and compile the generator
        self.generator = self.build_generator()
        self.generator.compile(loss=['binary_crossentropy'],
            optimizer=optimizer)

        # The generator takes noise as input and generates imgs
        masked_img = Input(shape=self.img_shape)
        gen_img = self.generator(masked_img)

        # For the combined model we will only train the generator
        self.discriminator.trainable = False

        # The valid takes generated images as input and determines validity
        valid, _ = self.discriminator(gen_img)

        # The combined model  (stacked generator and discriminator) takes
        # masked_img as input => generates images => determines validity
        self.combined = Model(masked_img , valid)
        self.combined.compile(loss=['mse'],
            optimizer=optimizer)


    def build_generator(self):
        """U-Net Generator"""

        input_img = Input(shape=self.img_shape)

        # (32 x 32 x 1)
        d1 = Conv2D(32, kernel_size=4, strides=2, padding='same', input_shape=self.img_shape)(input_img)
        d1 = LeakyReLU(alpha=0.2)(d1)
        d1 = InstanceNormalization()(d1)
        # (16 x 16 x 32)
        d2 = Conv2D(64, kernel_size=4, strides=2, padding='same')(d1)
        d2 = LeakyReLU(alpha=0.2)(d2)
        d2 = InstanceNormalization()(d2)
        # (8 x 8 x 64)
        d3 = Conv2D(128, kernel_size=4, strides=2, padding='same')(d2)
        d3 = LeakyReLU(alpha=0.2)(d3)
        d3 = InstanceNormalization()(d3)
        # (4 x 4 x 128)
        d4 = Conv2D(256, kernel_size=4, strides=2, padding='same')(d3)
        d4 = LeakyReLU(alpha=0.2)(d4)
        d4 = InstanceNormalization()(d4)
        # (2 x 2 x 256)
        u1 = UpSampling2D(size=2)(d4)
        u1 = Conv2D(128, kernel_size=4, strides=1, padding='same')(u1)
        u1 = LeakyReLU(alpha=0.2)(u1)
        u1 = InstanceNormalization()(u1)
        u1 = Concatenate()([u1, d3]) 
        # (4 x 4 x 256)
        u2 = UpSampling2D(size=2)(u1)
        u2 = Conv2D(64, kernel_size=4, strides=1, padding='same')(u2)
        u2 = LeakyReLU(alpha=0.2)(u2)
        u2 = InstanceNormalization()(u2)
        u2 = Concatenate()([u2, d2])
        # (8 x 8 x 128)
        u3 = UpSampling2D(size=2)(u2)
        u3 = Conv2D(32, kernel_size=4, strides=1, padding='same')(u3)
        u3 = LeakyReLU(alpha=0.2)(u3)
        u3 = InstanceNormalization()(u3)
        u3 = Concatenate()([u3, d1])
        # (16 x 16 x 64)
        u2 = UpSampling2D(size=2)(u3)
        output_img = Conv2D(self.channels, kernel_size=4, strides=1, padding='same', activation='tanh')(u2)

        return Model(input_img, output_img)

    def build_discriminator(self):

        img = Input(shape=self.img_shape)

        model = Sequential()
        model.add(Conv2D(64, kernel_size=4, strides=2, padding='same', input_shape=self.img_shape))
        model.add(LeakyReLU(alpha=0.8))
        model.add(Conv2D(128, kernel_size=4, strides=2, padding='same'))
        model.add(LeakyReLU(alpha=0.2))
        model.add(InstanceNormalization())
        model.add(Conv2D(256, kernel_size=4, strides=2, padding='same'))
        model.add(LeakyReLU(alpha=0.2))
        model.add(InstanceNormalization())

        model.summary()

        img = Input(shape=self.img_shape)
        features = model(img)

        validity = Conv2D(1, kernel_size=4, strides=1, padding='same')(features)

        label = Flatten()(features)
        label = Dense(self.num_classes+1, activation="softmax")(label)

        return Model(img, [validity, label])

    def mask_randomly(self, imgs):
        y1 = np.random.randint(0, self.img_rows - self.mask_height, imgs.shape[0])
        y2 = y1 + self.mask_height
        x1 = np.random.randint(0, self.img_rows - self.mask_width, imgs.shape[0])
        x2 = x1 + self.mask_width

        masked_imgs = np.empty_like(imgs)
        for i, img in enumerate(imgs):
            masked_img = img.copy()
            _y1, _y2, _x1, _x2 = y1[i], y2[i], x1[i], x2[i],
            masked_img[_y1:_y2, _x1:_x2, :] = 0
            masked_imgs[i] = masked_img

        return masked_imgs


    def train(self, epochs, batch_size=128, save_interval=50):

        # Load the dataset

        # Load the dataset
        (X_train, y_train), (_, _) = mnist.load_data()

        # Rescale MNIST to 32x32
        X_train = np.array([scipy.misc.imresize(x, [self.img_rows, self.img_cols]) for x in X_train])

        # Rescale -1 to 1
        X_train = (X_train.astype(np.float32) - 127.5) / 127.5
        X_train = np.expand_dims(X_train, axis=3)
        y_train = y_train.reshape(-1, 1)

        half_batch = int(batch_size / 2)

        for epoch in range(epochs):


            # ---------------------
            #  Train Discriminator
            # ---------------------

            # Sample half batch of images
            idx = np.random.randint(0, X_train.shape[0], half_batch)
            imgs = X_train[idx]
            labels = y_train[idx]

            masked_imgs = self.mask_randomly(imgs)

            # Generate a half batch of new images
            gen_imgs = self.generator.predict(masked_imgs)

            valid = np.ones((half_batch, 4, 4, 1))
            fake = np.zeros((half_batch, 4, 4, 1))

            labels = to_categorical(labels, num_classes=self.num_classes+1)
            fake_labels = to_categorical(np.full((half_batch, 1), self.num_classes), num_classes=self.num_classes+1)

            # Train the discriminator
            d_loss_real = self.discriminator.train_on_batch(imgs, [valid, labels])
            d_loss_fake = self.discriminator.train_on_batch(gen_imgs, [fake, fake_labels])
            d_loss = 0.5 * np.add(d_loss_real, d_loss_fake)


            # ---------------------
            #  Train Generator
            # ---------------------

            # Select a random half batch of images
            idx = np.random.randint(0, X_train.shape[0], batch_size)
            imgs = X_train[idx]

            masked_imgs = self.mask_randomly(imgs)

            # Generator wants the discriminator to label the generated images as valid
            valid = np.ones((batch_size, 4, 4, 1))

            # Train the generator
            g_loss = self.combined.train_on_batch(masked_imgs, valid)

            # Plot the progress
            print ("%d [D loss: %f, op_acc: %.2f%%] [G loss: %f]" % (epoch, d_loss[0], 100*d_loss[4], g_loss))

            # If at save interval => save generated image samples
            if epoch % save_interval == 0:
                # Select a random half batch of images
                idx = np.random.randint(0, X_train.shape[0], 6)
                imgs = X_train[idx]
                self.save_imgs(epoch, imgs)
                self.save_model()


    def save_imgs(self, epoch, imgs):
        r, c = 3, 6

        masked_imgs = self.mask_randomly(imgs)
        gen_imgs = self.generator.predict(masked_imgs)

        imgs = (imgs + 1.0) * 0.5
        masked_imgs = (masked_imgs + 1.0) * 0.5
        gen_imgs = (gen_imgs + 1.0) * 0.5

        gen_imgs = np.where(gen_imgs < 0, 0, gen_imgs)

        fig, axs = plt.subplots(r, c)
        for i in range(c):
            axs[0,i].imshow(imgs[i, :, :, 0], cmap='gray')
            axs[0,i].axis('off')
            axs[1,i].imshow(masked_imgs[i, :, :, 0], cmap='gray')
            axs[1,i].axis('off')
            axs[2,i].imshow(gen_imgs[i, :, :, 0], cmap='gray')
            axs[2,i].axis('off')
        fig.savefig("ccgan/images/cifar_%d.png" % epoch)
        plt.close()

    def save_model(self):

        def save(model, model_name):
            model_path = "ccgan/saved_model/%s.json" % model_name
            weights_path = "ccgan/saved_model/%s_weights.hdf5" % model_name
            options = {"file_arch": model_path,
                        "file_weight": weights_path}
            json_string = model.to_json()
            open(options['file_arch'], 'w').write(json_string)
            model.save_weights(options['file_weight'])

        save(self.generator, "ccgan_generator")
        save(self.discriminator, "ccgan_discriminator")


if __name__ == '__main__':
    ccgan = CCGAN()
    ccgan.train(epochs=20000, batch_size=16, save_interval=50)
