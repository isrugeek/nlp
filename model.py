import numpy as np
import tensorflow as tf

from tensorflow.python.ops.nn import dynamic_rnn
from tensorflow.contrib.seq2seq.python.ops.loss import sequence_loss
from tensorflow.contrib.lookup.lookup_ops import MutableHashTable
from tensorflow.contrib.layers.python.layers import layers
from tensorflow.contrib.session_bundle import exporter

from rnn_cell import GRUCell, BasicLSTMCell, MultiRNNCell, BasicRNNCell

PAD_ID = 0
UNK_ID = 1
_START_VOCAB = ['_PAD', '_UNK']

class RNN(object):
    def __init__(self,
            num_symbols,
            num_embed_units,
            num_units,
            num_layers,
            num_labels,
            embed,
            learning_rate=0.005,
            max_gradient_norm=5.0,
			param_da=150,
			param_r=10):

        self.texts = tf.placeholder(tf.string, (None, None), 'texts')  # shape: [batch, length]

        #todo: implement placeholders
        self.texts_length = tf.placeholder(tf.int32,(None), 'texts_length')  # shape: [batch]
        self.labels = tf.placeholder(tf.int64,(None), 'labels')  # shape: [batch]

        self.symbol2index = MutableHashTable(
                key_dtype=tf.string,
                value_dtype=tf.int64,
                default_value=UNK_ID,
                shared_name="in_table",
                name="in_table",
                checkpoint=True)

        batch_size = tf.shape(self.texts)[0]
        # build the vocab table (string to index)
        # initialize the training process
        self.learning_rate = tf.Variable(float(learning_rate),
                trainable=False, dtype=tf.float32)
        self.global_step = tf.Variable(0, trainable=False)


        self.index_input = self.symbol2index.lookup(self.texts)   # shape: [batch, length]

        # build the embedding table (index to vector)
        if embed is None:
            # initialize the embedding randomly
            self.embed = tf.get_variable('embed', [num_symbols, num_embed_units], tf.float32)
        else:
            # initialize the embedding by pre-trained word vectors
            self.embed = tf.get_variable('embed', dtype=tf.float32, initializer=embed)

        #todo: implement embedding inputs
        self.embed_input = tf.nn.embedding_lookup(self.embed, self.index_input)


        #shape: [batch, length, num_embed_units]


        #todo: implement Multi-layer RNNCell with #num_units neurons and #num_layers layers
        cell_fw = MultiRNNCell([BasicLSTMCell(num_units) for _ in range(num_layers)])
        cell_bw = MultiRNNCell([BasicLSTMCell(num_units) for _ in range(num_layers)])

        #todo: implement bidirectional RNN
        outputs, states = tf.nn.bidirectional_dynamic_rnn(cell_fw,cell_bw,self.embed_input ,self.texts_length ,  dtype=tf.float32, scope="rnn")
        vectors = states[-1][-1]
        print ("Hi")
        H = tf.concat(outputs, 2) # shape: (batch, length, 2*num_units)


        with tf.variable_scope('logits'):
            #todo: implement self-attention mechanism, feel free to add codes to calculate internal results
            Ws1 = tf.get_variable("Ws1", shape = [2*num_units, param_da])
            Ws2 = tf.get_variable("Ws2", shape = [param_da, param_r])
            #param1 = tf.matmul(vectors,Ws1) + Ws2
            #print(Ws1,Ws2)

            A = tf.nn.softmax(tf.einsum('aij,jk->aik',tf.nn.tanh(tf.einsum('aij,jk->aik',H,Ws1)),Ws2))
            #M = tf.matmul(H,Ws1) + Ws2   # shape: (batch, param_r*2*num_units)
            M = tf.einsum('aij,aik->ajk',A,H)
            #M=tf.reduce_sum(M, axis=1)
            M = tf.reshape(M,[batch_size,param_r*2*num_units])
            logits = tf.layers.dense(M, num_labels, activation=None, name='projection') # shape: (batch, num_labels)
            #logits = tf.layers.dense(M, num_labels, activation=None, name='projection') # shape: (batch, num_labels)
        #todo: calculate additional loss, feel free to add codes to calculate internal results
        identity = tf.reshape(tf.tile(tf.diag(tf.ones([param_r])), [batch_size, 1]), [batch_size, param_r, param_r])
        #self.penalized_term = tf.nnl2_loss(M,name=None)
        P = tf.einsum("aij,ajk->aik",tf.einsum("aij->aji",A),A) - identity
        self.penalized_term = tf.reduce_mean(tf.trace(tf.einsum("aij,ajk->aik", tf.einsum("aij->aji",P),P)))




        self.loss = tf.reduce_sum(tf.nn.sparse_softmax_cross_entropy_with_logits(labels=self.labels, logits=logits), name='loss') + 0.0001*self.penalized_term
        predict_labels = tf.argmax(logits, 1, 'predict_labels')
        self.accuracy = tf.reduce_sum(tf.cast(tf.equal(self.labels, predict_labels), tf.int32), name='accuracy')

        self.params = tf.trainable_variables()

        # calculate the gradient of parameters
        opt = tf.train.GradientDescentOptimizer(self.learning_rate)
        gradients = tf.gradients(self.loss, self.params)
        clipped_gradients, self.gradient_norm = tf.clip_by_global_norm(gradients,
                max_gradient_norm)
        self.update = opt.apply_gradients(zip(clipped_gradients, self.params),
                global_step=self.global_step)

        self.saver = tf.train.Saver(write_version=tf.train.SaverDef.V2,
                max_to_keep=5, pad_step_number=True)

    def print_parameters(self):
        for item in self.params:
            print('%s: %s' % (item.name, item.get_shape()))

    def train_step(self, session, data):
        input_feed = {self.texts: data['texts'],
                self.texts_length: data['texts_length'],
                self.labels: data['labels']}
        output_feed = [self.loss, self.accuracy, self.gradient_norm, self.update]
        return session.run(output_feed, input_feed)
