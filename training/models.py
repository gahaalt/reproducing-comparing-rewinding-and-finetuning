from collections.abc import Iterable

import tensorflow as tf


def classifier(
    flow,
    n_classes,
    regularizer=None,
    bias_regularizer=None,
    initializer="glorot_uniform",
    pooling="avgpool",
):
    if pooling == "catpool":
        maxp = tf.keras.layers.GlobalMaxPool2D()(flow)
        avgp = tf.keras.layers.GlobalAvgPool2D()(flow)
        flow = tf.keras.layers.Concatenate()([maxp, avgp])
    if pooling == "avgpool":
        flow = tf.keras.layers.GlobalAvgPool2D()(flow)
    if pooling == "maxpool":
        flow = tf.keras.layers.GlobalMaxPool2D()(flow)

    # multiple-head version
    if isinstance(n_classes, Iterable):
        outs = [
            tf.keras.layers.Dense(
                n_class,
                bias_regularizer=bias_regularizer,
                kernel_regularizer=regularizer,
                kernel_initializer=initializer,
            )(flow)
            for n_class in n_classes
        ]
    else:
        outs = tf.keras.layers.Dense(
            n_classes,
            bias_regularizer=bias_regularizer,
            kernel_regularizer=regularizer,
            kernel_initializer=initializer,
        )(flow)
    return outs


def ResNetStiff(
    dataset=None,
    alias=None,
    input_shape=None,
    n_classes=None,
    resnet_version=2,
    features=(16, 32, 64),
    l1_reg=0,
    l2_reg=2e-4,
    initializer="he_uniform",
    activation="tf.nn.relu",
    BLOCKS_IN_GROUP=3,
    BATCH_NORM_DECAY=0.997,  # 0.9
    BATCH_NORM_EPSILON=1e-5,  # 1e-3
    final_pooling="avgpool",
    dropout=0,
    regularize_bias=True,
    shortcut_conv_projection=True,
):
    if dataset == 'cifar' or dataset == 'cifar10':
        input_shape = (32, 32, 3)
        n_classes = 10
    elif dataset == 'cifar100':
        input_shape = (32, 32, 3)
        n_classes = 100
    elif dataset == 'mnist':
        input_shape = (28, 28, 1)
        n_classes = 10
    else:
        assert input_shape is not None
        assert n_classes is not None

    if alias == 'WRN-16-8':
        N = 16
        K = 8
        assert (N - 4) % 6 == 0
        size = int((N - 4) / 6)
        BLOCKS_IN_GROUP = size
        features = (16 * K, 32 * K, 64 * K),

    activation_func = eval(activation)
    if l2_reg or l1_reg:
        regularizer = tf.keras.regularizers.l1_l2(l1_reg, l2_reg)
    else:
        regularizer = None
    bias_regularizer = regularizer if regularize_bias else None

    def conv(filters, kernel_size, use_bias=False, **kwds):
        return tf.keras.layers.Conv2D(
            filters,
            kernel_size,
            padding="same",
            use_bias=use_bias,
            kernel_initializer=initializer,
            kernel_regularizer=regularizer,
            bias_regularizer=bias_regularizer,
            **kwds,
        )

    def shortcut(x, filters, strides):
        if not shortcut_conv_projection:
            m_filters = filters - x.shape[-1]
            m_width = x.shape[1] // strides
            m_height = x.shape[2] // strides
            return tf.pad(
                x[:, :m_width, :m_height], [[0, 0], [0, 0], [0, 0], [m_filters, 0]]
            )
        else:
            return tf.keras.layers.Conv2D(
                filters,
                kernel_size=1,
                use_bias=False,
                strides=strides,
                kernel_initializer=initializer,
                kernel_regularizer=regularizer,
            )(x)

    def bn_activate(x, remove_relu=False):
        x = tf.keras.layers.BatchNormalization(
            beta_regularizer=bias_regularizer, gamma_regularizer=bias_regularizer,
            momentum=BATCH_NORM_DECAY, epsilon=BATCH_NORM_EPSILON,
        )(x)
        return x if remove_relu else activation_func(x)

    def simple_block2(flow,
                      filters,
                      strides,
                      activate_shortcut=False):
        flow_shortcut = flow
        flow = bn_activate(flow)
        if activate_shortcut:
            flow_shortcut = flow
        if flow.shape[-1] != filters or strides != 1:
            flow_shortcut = shortcut(flow_shortcut, filters, strides)

        flow = conv(filters, 3, strides=strides)(flow)
        flow = bn_activate(flow)

        if dropout:
            flow = tf.keras.layers.Dropout(dropout)(flow)
        flow = conv(filters, 3, strides=1)(flow)
        return flow + flow_shortcut

    def simple_block1(flow, filters, strides):
        flow_shortcut = flow
        if flow.shape[-1] != filters or strides != 1:
            flow_shortcut = shortcut(flow, filters, strides)
            flow_shortcut = bn_activate(flow_shortcut, remove_relu=True)

        flow = conv(filters, 3, strides=strides)(flow)
        flow = bn_activate(flow)

        if dropout:
            flow = tf.keras.layers.Dropout(dropout)(flow)
        flow = conv(filters, 3, strides=1)(flow)
        flow = bn_activate(flow, remove_relu=True)
        return activation_func(flow + flow_shortcut)

    inputs = tf.keras.Input(input_shape)
    flow = inputs

    flow = conv(16, 3, strides=1, use_bias=False)(flow)

    if resnet_version == 2:
        flow = simple_block2(flow,
                             filters=features[0],
                             strides=1,
                             activate_shortcut=True)
        for _ in range(BLOCKS_IN_GROUP - 1):
            flow = simple_block2(flow, filters=features[0], strides=1)

        flow = simple_block2(flow,
                             filters=features[1],
                             strides=2,
                             activate_shortcut=True)
        for _ in range(BLOCKS_IN_GROUP - 1):
            flow = simple_block2(flow, filters=features[1], strides=1)

        flow = simple_block2(flow,
                             filters=features[2],
                             strides=2,
                             activate_shortcut=True)
        for _ in range(BLOCKS_IN_GROUP - 1):
            flow = simple_block2(flow, filters=features[2], strides=1)

        flow = bn_activate(flow, remove_relu=True)
        flow = tf.nn.relu(flow)

    elif resnet_version == 1:
        flow = bn_activate(flow)

        flow = simple_block1(flow, filters=features[0], strides=1)
        for _ in range(BLOCKS_IN_GROUP - 1):
            flow = simple_block1(flow, filters=features[0], strides=1)

        flow = simple_block1(flow, filters=features[1], strides=2)
        for _ in range(BLOCKS_IN_GROUP - 1):
            flow = simple_block1(flow, filters=features[1], strides=1)

        flow = simple_block1(flow, filters=features[2], strides=2)
        for _ in range(BLOCKS_IN_GROUP - 1):
            flow = simple_block1(flow, filters=features[2], strides=1)

    outputs = classifier(
        flow,
        n_classes,
        regularizer=regularizer,
        bias_regularizer=bias_regularizer,
        initializer=initializer,
        pooling=final_pooling,
    )
    model = tf.keras.Model(inputs=inputs, outputs=outputs)
    return model
