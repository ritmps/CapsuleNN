"""
Capsule Networks as Recurrent Models of Grouping and Segmentation

Experiment 2: The role of recurrent processing

This is the model function used for the Estimator API of tensorflow
(see capser_main.py).
More detailed information about all called functions can be found in
capser_functions.py
For more information about the Estimator API, look at:
https://www.tensorflow.org/guide/estimators

@author: Lynn Schmittwilken
"""

import tensorflow as tf

from parameters import parameters
from capser_functions import \
conv_layers, primary_caps_layer, secondary_caps_layer, \
predict_shapelabels, create_masked_decoder_input, compute_margin_loss, \
compute_accuracy, compute_reconstruction, compute_reconstruction_loss, \
compute_vernieroffset_loss


def model_fn(features, labels, mode, params):
    # features: This is the x-arg from the input_fn.
    # labels:   This is the y-arg from the input_fn.
    # mode:     Either TRAIN, EVAL, or PREDICT
    # params:   Optional parameters; here not needed because of parameter-file
    
    ##########################################
    #      Prepararing input variables:      #
    ##########################################
    log_dir = params['log_dir']
    iter_routing = params['iter_routing']
    shape_1_images = tf.cast(features['shape_1_images'], tf.float32)
    shape_2_images = tf.cast(features['shape_2_images'], tf.float32)
    shapelabels = tf.cast(features['shapelabels'], tf.int64)
    nshapeslabels = tf.cast(features['nshapeslabels'], tf.int64)
    vernierlabels = tf.cast(features['vernier_offsets'], tf.int64)
    mask_with_labels = tf.placeholder_with_default(features['mask_with_labels'], shape=(), name='mask_with_labels')
    is_training = tf.placeholder_with_default(features['is_training'], shape=(), name='is_training')
    
    input_images = tf.add(shape_1_images, shape_2_images, name='input_images')
    input_images = tf.clip_by_value(input_images, parameters.clip_values[0], parameters.clip_values[1], name='input_images_clipped')
    
    # Plot each four (reconstructed) input images in tensorboard
    plot_n_images = 4
    tf.summary.image('full_input_images', input_images, plot_n_images)


    # In case we provided a batch_size via params, use it
    try:
        batch_size = params['batch_size']
    except:
        batch_size = parameters.batch_size

    # How many different shape types are expected in the image?
    if mode == tf.estimator.ModeKeys.PREDICT:
        n_shapes  = shapelabels.shape[1]
        
    else:
        # In this code, we only use the 'random' train_procedure
        if parameters.train_procedure=='vernier_shape' or parameters.train_procedure=='random_random':
            n_shapes  = shapelabels.shape[1]
    
        elif parameters.train_procedure=='random':
            # For the random condition, we only use shape_1 during train and eval
            n_shapes = 1
            shapelabels = shapelabels[:, 0]
            nshapeslabels = nshapeslabels[:, 0]
    
        else:
            raise SystemExit('\nThe chosen train_procedure is unknown!\n')


    ##########################################
    #          Build the capsnet:            #
    ##########################################
    # Create convolutional layers and their output:
    conv_output, conv_output_sizes = conv_layers(input_images, parameters, is_training)
    
    # Create primary caps and their output:
    caps1_output = primary_caps_layer(conv_output, parameters)
    
    # Create secondary caps and compute their output.
    # Also, we need the individual outputs of the vernier caps and shape caps
    caps2_output, caps2_output_norm = secondary_caps_layer(caps1_output, batch_size, iter_routing, parameters)
    shape_1_caps_activation = caps2_output[:, :, 0, :, :]
    shape_1_caps_activation = tf.expand_dims(shape_1_caps_activation, 2)

    # Compute vernier acuity based on the secondary vernier capsule outputs
    with tf.name_scope('1_vernier_acuity'):
        vernierlabels_pred, vernieroffset_loss, vernieroffset_accuracy = compute_vernieroffset_loss(shape_1_caps_activation,
                                                                                                    vernierlabels, parameters,
                                                                                                    is_training)
        
        # Visualizations in tensorboard
        vernieroffset_loss = parameters.alpha_vernieroffset * vernieroffset_loss
        tf.summary.scalar('vernieroffset_loss', vernieroffset_loss)
        tf.summary.scalar('vernieroffset_accuracy', vernieroffset_accuracy)
        tf.summary.histogram('vernierlabels_pred', vernierlabels_pred)
        tf.summary.histogram('vernierlabels_real', vernierlabels)
    
    
    ##########################################
    #             Predict shapes             #
    ##########################################
    # How many shapes have to be predicted? Predict them:
        with tf.name_scope('2_predict_shapes'):
            shapelabels_pred = predict_shapelabels(caps2_output, n_shapes)[0]
            
            # For prediction: give me a ranking of most probably shapes:
            rank_pred_shapes, rank_pred_proba = predict_shapelabels(caps2_output, len(parameters.shape_types))
    
    
    ##########################################
    #     Create masked decoder input        #
    ##########################################
    with tf.name_scope('3_Masked_decoder_input'):
        if n_shapes==2:
            shape_1_decoder_input = create_masked_decoder_input(
                    mask_with_labels, shapelabels[:, 0], shapelabels_pred[:, 0], caps2_output, parameters)
            shape_2_decoder_input = create_masked_decoder_input(
                    mask_with_labels, shapelabels[:, 1], shapelabels_pred[:, 1], caps2_output, parameters)
            
        elif n_shapes==1:
            shape_1_decoder_input = create_masked_decoder_input(
                    mask_with_labels, shapelabels, shapelabels_pred, caps2_output, parameters)


    ##########################################
    #         Decode reconstruction          #
    ##########################################
    with tf.name_scope('4_Reconstruction_loss'):
        if parameters.decode_reconstruction:
            if n_shapes==2:
                # Create decoder outputs for shape_1 and shape_2 images
                shape_1_output_reconstructed = compute_reconstruction(shape_1_decoder_input, parameters, is_training, conv_output_sizes)
                shape_2_output_reconstructed = compute_reconstruction(shape_2_decoder_input, parameters, is_training, conv_output_sizes)
                
                shape_1_img_reconstructed = tf.reshape(
                        shape_1_output_reconstructed,
                        [batch_size, parameters.im_size[0], parameters.im_size[1], parameters.im_depth],
                        name='shape_1_img_reconstructed')
                shape_2_img_reconstructed = tf.reshape(
                        shape_2_output_reconstructed,
                        [batch_size, parameters.im_size[0], parameters.im_size[1], parameters.im_depth],
                        name='shape_2_img_reconstructed')

                # Create an rgb tf.summary image for tensorboard
                color_masks = tf.cast(tf.convert_to_tensor([[121, 199, 83],  # 0: vernier, green
                                                            [220, 76, 70],   # 1: red
                                                            [79, 132, 196]]), tf.float32)  # 3: blue
                color_masks = tf.expand_dims(color_masks, axis=1)
                color_masks = tf.expand_dims(color_masks, axis=1)
                decoder_output_images_rgb_0 = tf.image.grayscale_to_rgb(shape_1_img_reconstructed) * color_masks[0, :, :, :]
                decoder_output_images_rgb_1 = tf.image.grayscale_to_rgb(shape_2_img_reconstructed) * color_masks[1, :, :, :]

                # Visualizations in tensorboard
                decoder_output_img = decoder_output_images_rgb_0 + decoder_output_images_rgb_1
                tf.summary.image('decoder_output_img', decoder_output_img, plot_n_images)
                
                # Calculate reconstruction loss for shape_1 and shape_2 images batch
                shape_1_reconstruction_loss = compute_reconstruction_loss(shape_1_images, shape_1_output_reconstructed, parameters)
                shape_2_reconstruction_loss = compute_reconstruction_loss(shape_2_images, shape_2_output_reconstructed, parameters)
                
                shape_1_reconstruction_loss = parameters.alpha_shape_1_reconstruction * shape_1_reconstruction_loss
                shape_2_reconstruction_loss = parameters.alpha_shape_2_reconstruction * shape_2_reconstruction_loss
                reconstruction_loss = shape_1_reconstruction_loss + shape_2_reconstruction_loss


            elif n_shapes==1:
                # Create decoder outputs for shape_1 images
                shape_1_output_reconstructed = compute_reconstruction(shape_1_decoder_input, parameters, is_training, conv_output_sizes)
                
                decoder_output_img = tf.reshape(
                        shape_1_output_reconstructed,
                        [batch_size, parameters.im_size[0], parameters.im_size[1], parameters.im_depth],
                        name='shape_1_img_reconstructed')
    
                # Visualizations in tensorboard
                tf.summary.image('decoder_output_img', decoder_output_img, plot_n_images)
                
                # Calculate reconstruction loss for shape_1 images
                shape_1_reconstruction_loss = compute_reconstruction_loss(shape_1_images, shape_1_output_reconstructed, parameters)
                
                shape_1_reconstruction_loss = parameters.alpha_shape_1_reconstruction * shape_1_reconstruction_loss
                shape_2_reconstruction_loss = 0.
                reconstruction_loss = shape_1_reconstruction_loss + shape_2_reconstruction_loss

        else:
            shape_1_reconstruction_loss = 0.
            shape_2_reconstruction_loss = 0.
            reconstruction_loss = 0.

        # Visualizations in tensorboard
        tf.summary.scalar('shape_1_reconstruction_loss', shape_1_reconstruction_loss)
        tf.summary.scalar('shape_2_reconstruction_loss', shape_2_reconstruction_loss)
        tf.summary.scalar('reconstruction_loss', reconstruction_loss)
    
    
    ##########################################
    #            Prediction mode:            #
    ##########################################
    if mode == tf.estimator.ModeKeys.PREDICT:
          
        # If in prediction-mode use (one of) the following for predictions:
        # Since accuracy is calculated over whole batch, we have to repeat it
        # batch_size times (coz all prediction vectors must be same length)
        predictions = {'vernier_accuracy': tf.ones(shape=batch_size) * vernieroffset_accuracy,
                       'rank_pred_shapes': rank_pred_shapes,
                       'rank_pred_proba': rank_pred_proba}
        
        spec = tf.estimator.EstimatorSpec(mode=mode, predictions=predictions)


    ##########################################
    #       Train or Evaluation mode:        #
    ##########################################
    else:        
    ##########################################
    #             Margin loss                #
    ##########################################
    # How many shapes have to be predicted? Predict them:
        with tf.name_scope('5_margin'):
            # Compute accuracy:
            accuracy = compute_accuracy(shapelabels, shapelabels_pred)
            
            # Visualizations in tensorboard
            tf.summary.scalar('margin_accuracy', accuracy)

            # Define the loss-function to be optimized
            margin_loss = compute_margin_loss(caps2_output_norm, shapelabels, parameters)
            margin_loss = parameters.alpha_margin * margin_loss
            
            # Visualizations in tensorboard
            tf.summary.scalar('margin_loss', margin_loss)
    

    ##########################################
    #            Decode nshapes              #
    ##########################################
        with tf.name_scope('6_Nshapes_loss'):
            # Not usable in this project
            nshapes_loss = 0.
            nshapes_accuracy = 0.
                
            # Visualizations in tensorboard
            tf.summary.scalar('nshapes_loss', nshapes_loss)
            tf.summary.scalar('nshapes_accuracy', nshapes_accuracy)


    ##########################################
    #       Decode x and y coordinates       #
    ##########################################
        with tf.name_scope('7_Location_loss'):
            # Not usable in this project
            x_shape_1_loss = 0.
            y_shape_1_loss = 0.
            x_shape_2_loss = 0.
            y_shape_2_loss = 0.
            location_loss = 0.
            
            # Visualizations in tensorboard
            tf.summary.scalar('x_shape_1_loss', x_shape_1_loss)
            tf.summary.scalar('y_shape_1_loss', y_shape_1_loss)
            tf.summary.scalar('x_shape_2_loss', x_shape_2_loss)
            tf.summary.scalar('y_shape_2_loss', y_shape_2_loss)
            tf.summary.scalar('location_loss', location_loss)


    ##########################################
    #              Final loss                #
    ##########################################
        final_loss = tf.add_n([margin_loss,
                               shape_1_reconstruction_loss,
                               shape_2_reconstruction_loss,
                               vernieroffset_loss,
                               nshapes_loss,
                               location_loss],
                              name='final_loss')


    ##########################################
    #        Training operations             #
    ##########################################
        # The following is needed due to how tf.layers.batch_normalzation works:
        update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
        
        with tf.control_dependencies(update_ops):
            # Use a learning rate with cosine decay restarts
            learning_rate = tf.train.cosine_decay_restarts(parameters.learning_rate, tf.train.get_global_step(),
                                                           parameters.learning_rate_decay_steps, name='learning_rate')
            optimizer = tf.train.AdamOptimizer(learning_rate=learning_rate)
            train_op = optimizer.minimize(loss=final_loss, global_step=tf.train.get_global_step(), name='train_op')
            
            # Visualizations in tensorboard
            tf.summary.scalar('learning_rate', learning_rate)
        
        # Write summaries during evaluation
        eval_summary_hook = tf.train.SummarySaverHook(save_steps=100,
                                                      output_dir=log_dir + '/eval',
                                                      summary_op=tf.summary.merge_all())
        
        # Wrap all of this in an EstimatorSpec.
        spec = tf.estimator.EstimatorSpec(
            mode=mode,
            loss=final_loss,
            train_op=train_op,
            eval_metric_ops={},
            evaluation_hooks=[eval_summary_hook])
    
    return spec
