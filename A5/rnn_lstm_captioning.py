import math
from typing import Optional, Tuple

import torch
import torchvision
from torch import nn
from torch.nn import functional as F
from torchvision.models import feature_extraction


def hello_rnn_lstm_captioning():
    print("Hello from rnn_lstm_captioning.py!")


class ImageEncoder(nn.Module):
    """
    Convolutional network that accepts images as input and outputs their spatial
    grid features. This module servesx as the image encoder in image captioning
    model. We will use a tiny RegNet-X 400MF model that is initialized with
    ImageNet-pretrained weights from Torchvision library.

    NOTE: We could use any convolutional network architecture, but we opt for a
    tiny RegNet model so it can train decently with a single K80 Colab GPU.
    """

    def __init__(self, pretrained: bool = True, verbose: bool = True):
        """
        Args:
            pretrained: Whether to initialize this model with pretrained weights
                from Torchvision library.
            verbose: Whether to log expected output shapes during instantiation.
        """
        super().__init__()
        self.cnn = torchvision.models.regnet_x_400mf(pretrained=pretrained)

        # Torchvision models return global average pooled features by default.
        # Our attention-based models may require spatial grid features. So we
        # wrap the ConvNet with torchvision's feature extractor. We will get
        # the spatial features right before the final classification layer.
        self.backbone = feature_extraction.create_feature_extractor(
            self.cnn, return_nodes={"trunk_output.block4": "c5"}
        )
        # We call these features "c5", a name that may sound familiar from the
        # object detection assignment. :-)

        # Pass a dummy batch of input images to infer output shape.
        dummy_out = self.backbone(torch.randn(2, 3, 224, 224))["c5"]
        self._out_channels = dummy_out.shape[1]

        if verbose:
            print("For input images in NCHW format, shape (2, 3, 224, 224)")
            print(f"Shape of output c5 features: {dummy_out.shape}")

        # Input image batches are expected to be float tensors in range [0, 1].
        # However, the backbone here expects these tensors to be normalized by
        # ImageNet color mean/std (as it was trained that way).
        # We define a function to transform the input images before extraction:
        self.normalize = torchvision.transforms.Normalize(
            mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]
        )

    @property
    def out_channels(self):
        """
        Number of output channels in extracted image features. You may access
        this value freely to define more modules to go with this encoder.
        """
        return self._out_channels

    def forward(self, images: torch.Tensor):
        # Input images may be uint8 tensors in [0-255], change them to float
        # tensors in [0-1]. Get float type from backbone (could be float32/64).
        if images.dtype == torch.uint8:
            images = images.to(dtype=self.cnn.stem[0].weight.dtype)
            images /= 255.0

        # Normalize images by ImageNet color mean/std.
        images = self.normalize(images)

        # Extract c5 features from encoder (backbone) and return.
        # shape: (B, out_channels, H / 32, W / 32)
        features = self.backbone(images)["c5"]
        return features


##############################################################################
# Recurrent Neural Network                                                   #
##############################################################################
def rnn_step_forward(x, prev_h, Wx, Wh, b):
    """
    Run the forward pass for a single timestep of a vanilla RNN that uses a tanh
    activation function.

    The input data has dimension D, the hidden state has dimension H, and we use
    a minibatch size of N.

    Args:
        x: Input data for this timestep, of shape (N, D).
        prev_h: Hidden state from previous timestep, of shape (N, H)
        Wx: Weight matrix for input-to-hidden connections, of shape (D, H)
        Wh: Weight matrix for hidden-to-hidden connections, of shape (H, H)
        b: Biases, of shape (H,)

    Returns a tuple of:
        next_h: Next hidden state, of shape (N, H)
        cache: Tuple of values needed for the backward pass.
    """
    next_h, cache = None, None
    ##########################################################################
    # TODO: Implement a single forward step for the vanilla RNN. Store next
    # hidden state and any values you need for the backward pass in the next_h
    # and cache variables respectively.
    ##########################################################################
    # Replace "pass" statement with your code
    x_wx = x.mm(Wx) # (N, H)
    prev_wh = prev_h.mm(Wh) # (N, H)
    out = x_wx + prev_wh + b # (N, H)
    next_h = out.tanh()
    cache = (x, Wx, Wh, prev_h, next_h)
    ##########################################################################
    #                             END OF YOUR CODE                           #
    ##########################################################################
    return next_h, cache


def rnn_step_backward(dnext_h, cache):
    """
    Backward pass for a single timestep of a vanilla RNN.

    Args:
        dnext_h: Gradient of loss with respect to next hidden state, of shape (N, H)
        cache: Cache object from the forward pass

    Returns a tuple of:
        dx: Gradients of input data, of shape (N, D)
        dprev_h: Gradients of previous hidden state, of shape (N, H)
        dWx: Gradients of input-to-hidden weights, of shape (D, H)
        dWh: Gradients of hidden-to-hidden weights, of shape (H, H)
        db: Gradients of bias vector, of shape (H,)
    """
    dx, dprev_h, dWx, dWh, db = None, None, None, None, None
    ##########################################################################
    # TODO: Implement the backward pass for a single step of a vanilla RNN.
    #
    # HINT: For the tanh function, you can compute the local derivative in
    # terms of the output value from tanh.
    ##########################################################################
    # Replace "pass" statement with your code
    x, Wx, Wh, prev_h, next_h = cache # (N, D), (D, H), (H, H), (N, H), (N, H)
    dout = dnext_h * (1 - next_h ** 2) # (N, H)
    db = torch.sum(dout,axis = 0)
    dWh = (prev_h.T).mm(dout)
    dprev_h = dout.mm(Wh.T)
    dWx = (x.T).mm(dout)
    dx = dout.mm(Wx.T)
    ##########################################################################
    #                             END OF YOUR CODE                           #
    ##########################################################################
    return dx, dprev_h, dWx, dWh, db


def rnn_forward(x, h0, Wx, Wh, b):
    """
    Run a vanilla RNN forward on an entire sequence of data. We assume an input
    sequence composed of T vectors, each of dimension D. The RNN uses a hidden
    size of H, and we work over a minibatch containing N sequences. After running
    the RNN forward, we return the hidden states for all timesteps.

    Args:
        x: Input data for the entire timeseries, of shape (N, T, D).
        h0: Initial hidden state, of shape (N, H)
        Wx: Weight matrix for input-to-hidden connections, of shape (D, H)
        Wh: Weight matrix for hidden-to-hidden connections, of shape (H, H)
        b: Biases, of shape (H,)

    Returns a tuple of:
        h: Hidden states for the entire timeseries, of shape (N, T, H).
        cache: Values needed in the backward pass
    """
    h, cache = None, None
    ##########################################################################
    # TODO: Implement forward pass for a vanilla RNN running on a sequence of
    # input data. You should use the rnn_step_forward function that you defined
    # above. You can use a for loop to help compute the forward pass.
    ##########################################################################
    # Replace "pass" statement with your code
    N, T, D = x.shape
    N, H = h0.shape
    h = x.new_zeros((N, T, H))
    hi = h0
    cache = []
    for i in range(T):
        xi = x[:, i, :].squeeze()
        hi, cache_i = rnn_step_forward(xi, hi, Wx, Wh, b)
        h[:, i, :] = hi
        cache.append(cache_i)
    ##########################################################################
    #                             END OF YOUR CODE                           #
    ##########################################################################
    return h, cache


def rnn_backward(dh, cache):
    """
    Compute the backward pass for a vanilla RNN over an entire sequence of data.

    Args:
        dh: Upstream gradients of all hidden states, of shape (N, T, H).

    NOTE: 'dh' contains the upstream gradients produced by the
    individual loss functions at each timestep, *not* the gradients
    being passed between timesteps (which you'll have to compute yourself
    by calling rnn_step_backward in a loop).

    Returns a tuple of:
        dx: Gradient of inputs, of shape (N, T, D)
        dh0: Gradient of initial hidden state, of shape (N, H)
        dWx: Gradient of input-to-hidden weights, of shape (D, H)
        dWh: Gradient of hidden-to-hidden weights, of shape (H, H)
        db: Gradient of biases, of shape (H,)
    """
    dx, dh0, dWx, dWh, db = None, None, None, None, None
    ##########################################################################
    # TODO: Implement the backward pass for a vanilla RNN running an entire
    # sequence of data. You should use the rnn_step_backward function that you
    # defined above. You can use a for loop to help compute the backward pass.
    ##########################################################################
    # Replace "pass" statement with your code
    N, T, H = dh.shape
    dxl, dprev_h, dWx, dWh, db = rnn_step_backward(dh[:,T-1,:], cache[T-1])
    _, D = dxl.shape
    dx = dh.new_zeros((N, T, D))
    dx[:, T-1, :] = dxl
    for i in range(T-2, -1, -1):
        dxi, dprev_hi, dWxi, dWhi, dbi = rnn_step_backward(dh[:,i,:]+dprev_h, cache[i])
        dx[:,i,:] = dxi
        dprev_h = dprev_hi
        dWx += dWxi
        dWh += dWhi
        db += dbi
    dh0 = dprev_h
    ##########################################################################
    #                             END OF YOUR CODE                           #
    ##########################################################################
    return dx, dh0, dWx, dWh, db


class RNN(nn.Module):
    """
    Single-layer vanilla RNN module.

    You don't have to implement anything here but it is highly recommended to
    read through the code as you will implement subsequent modules.
    """

    def __init__(self, input_dim: int, hidden_dim: int):
        """
        Initialize an RNN. Model parameters to initialize:
            Wx: Weight matrix for input-to-hidden connections, of shape (D, H)
            Wh: Weight matrix for hidden-to-hidden connections, of shape (H, H)
            b: Biases, of shape (H,)

        Args:
            input_dim: Input size, denoted as D before
            hidden_dim: Hidden size, denoted as H before
        """
        super().__init__()

        # Register parameters
        self.Wx = nn.Parameter(
            torch.randn(input_dim, hidden_dim).div(math.sqrt(input_dim))
        )
        self.Wh = nn.Parameter(
            torch.randn(hidden_dim, hidden_dim).div(math.sqrt(hidden_dim))
        )
        self.b = nn.Parameter(torch.zeros(hidden_dim))

    def forward(self, x, h0):
        """
        Args:
            x: Input data for the entire timeseries, of shape (N, T, D)
            h0: Initial hidden state, of shape (N, H)

        Returns:
            hn: The hidden state output
        """
        hn, _ = rnn_forward(x, h0, self.Wx, self.Wh, self.b)
        return hn

    def step_forward(self, x, prev_h):
        """
        Args:
            x: Input data for one time step, of shape (N, D)
            prev_h: The previous hidden state, of shape (N, H)

        Returns:
            next_h: The next hidden state, of shape (N, H)
        """
        next_h, _ = rnn_step_forward(x, prev_h, self.Wx, self.Wh, self.b)
        return next_h


class WordEmbedding(nn.Module):
    """
    Simplified version of torch.nn.Embedding.

    We operate on minibatches of size N where
    each sequence has length T. We assume a vocabulary of V words, assigning each
    word to a vector of dimension D.

    Args:
        x: Integer array of shape (N, T) giving indices of words. Each element idx
      of x muxt be in the range 0 <= idx < V.

    Returns a tuple of:
        out: Array of shape (N, T, D) giving word vectors for all input words.
    """

    def __init__(self, vocab_size: int, embed_size: int):
        super().__init__()

        # Register parameters
        self.W_embed = nn.Parameter(
            torch.randn(vocab_size, embed_size).div(math.sqrt(vocab_size))
        )

    def forward(self, x):

        out = None
        ######################################################################
        # TODO: Implement the forward pass for word embeddings.
        ######################################################################
        # Replace "pass" statement with your code
        out = self.W_embed[x]
        ######################################################################
        #                           END OF YOUR CODE                         #
        ######################################################################
        return out


def temporal_softmax_loss(x, y, ignore_index=None):
    """
    A temporal version of softmax loss for use in RNNs. We assume that we are
    making predictions over a vocabulary of size V for each timestep of a
    timeseries of length T, over a minibatch of size N. The input x gives scores
    for all vocabulary elements at all timesteps, and y gives the indices of the
    ground-truth element at each timestep. We use a cross-entropy loss at each
    timestep, *summing* the loss over all timesteps and *averaging* across the
    minibatch.

    As an additional complication, we may want to ignore the model output at some
    timesteps, since sequences of different length may have been combined into a
    minibatch and padded with NULL tokens. The optional ignore_index argument
    tells us which elements in the caption should not contribute to the loss.

    Args:
        x: Input scores, of shape (N, T, V)
        y: Ground-truth indices, of shape (N, T) where each element is in the
            range 0 <= y[i, t] < V

    Returns a tuple of:
        loss: Scalar giving loss
    """
    loss = None

    ##########################################################################
    # TODO: Implement the temporal softmax loss function.
    #
    # REQUIREMENT: This part MUST be done in one single line of code!
    #
    # HINT: Look up the function torch.functional.cross_entropy, set
    # ignore_index to the variable ignore_index (i.e., index of NULL) and
    # set reduction to either 'sum' or 'mean' (avoid using 'none' for now).
    #
    # We use a cross-entropy loss at each timestep, *summing* the loss over
    # all timesteps and *averaging* across the minibatch.
    ##########################################################################
    # Replace "pass" statement with your 
    loss = F.cross_entropy(x.flatten(end_dim=1), y.flatten().to(torch.int64), reduction='sum', ignore_index=ignore_index) / x.shape[0]
    ##########################################################################
    #                             END OF YOUR CODE                           #
    ##########################################################################

    return loss


class CaptioningRNN(nn.Module):
    """
    A CaptioningRNN produces captions from images using a recurrent
    neural network.

    The RNN receives input vectors of size D, has a vocab size of V, works on
    sequences of length T, has an RNN hidden dimension of H, uses word vectors
    of dimension W, and operates on minibatches of size N.

    Note that we don't use any regularization for the CaptioningRNN.

    You will implement the `__init__` method for model initialization and
    the `forward` method first, then come back for the `sample` method later.
    """

    def __init__(
        self,
        word_to_idx,
        input_dim: int = 512,
        wordvec_dim: int = 128,
        hidden_dim: int = 128,
        cell_type: str = "rnn",
        image_encoder_pretrained: bool = True,
        ignore_index: Optional[int] = None,
    ):
        """
        Construct a new CaptioningRNN instance.

        Args:
            word_to_idx: A dictionary giving the vocabulary. It contains V
                entries, and maps each string to a unique integer in the
                range [0, V).
            input_dim: Dimension D of input image feature vectors.
            wordvec_dim: Dimension W of word vectors.
            hidden_dim: Dimension H for the hidden state of the RNN.
            cell_type: What type of RNN to use; either 'rnn' or 'lstm'.
        """
        super().__init__()
        if cell_type not in {"rnn", "lstm", "attn"}:
            raise ValueError('Invalid cell_type "%s"' % cell_type)

        self.cell_type = cell_type
        self.word_to_idx = word_to_idx
        self.idx_to_word = {i: w for w, i in word_to_idx.items()}

        vocab_size = len(word_to_idx)

        self._null = word_to_idx["<NULL>"]
        self._start = word_to_idx.get("<START>", None)
        self._end = word_to_idx.get("<END>", None)
        self.ignore_index = ignore_index

        ######################################################################
        # TODO: Initialize the image captioning module. Refer to the TODO
        # in the captioning_forward function on layers you need to create
        #
        # You may want to check the following pre-defined classes:
        # ImageEncoder WordEmbedding, RNN, LSTM, AttentionLSTM, nn.Linear
        #
        # (1) output projection (from RNN hidden state to vocab probability)
        # (2) feature projection (from CNN pooled feature to h0)
        ######################################################################
        # Replace "pass" statement with your code
        self.imageEncoder = ImageEncoder(image_encoder_pretrained)

        # Create a feature projector to h0 (in case of RNN and LSTM).
        # It transforms a tensor of shape (N, 1280) to (N, H).
        if self.cell_type in ['rnn', 'lstm']:
            self.featureProjector = nn.Linear(self.imageEncoder.out_channels, hidden_dim)
        else: # "cell_type" is 'attention'.
            # Transform a tensor of shape (N, 1280, 4, 4) to (N, H, 4, 4).
            self.featureProjector = nn.Conv2d(self.imageEncoder.out_channels, hidden_dim, 1, stride=1, padding=0)

        # Create a word embedding.
        self.wordEmbedding = WordEmbedding(vocab_size, wordvec_dim)

        # Create the core network, its type depends on the "cell_type".
        if self.cell_type == 'rnn':
          self.coreNetwork = RNN(wordvec_dim, hidden_dim)
        elif self.cell_type == 'lstm':
          self.coreNetwork = LSTM(wordvec_dim, hidden_dim)
        else: # "cell_type" is 'attention'.
          self.coreNetwork = AttentionLSTM(wordvec_dim, hidden_dim)

        # Create an output projector. It transforms the RNN hidden state to vocab probability.
        # In term of shapes, this layer [(H, V)] takes the input (N, T, H) and outputs (N, T, V)
        self.outProjector = nn.Linear(hidden_dim, vocab_size)
        ######################################################################
        #                            END OF YOUR CODE                        #
        ######################################################################

    def forward(self, images, captions):
        """
        Compute training-time loss for the RNN. We input images and the GT
        captions for those images, and use an RNN (or LSTM) to compute loss. The
        backward part will be done by torch.autograd.

        Args:
            images: Input images, of shape (N, 3, 112, 112)
            captions: Ground-truth captions; an integer array of shape (N, T + 1)
                where each element is in the range 0 <= y[i, t] < V

        Returns:
            loss: A scalar loss
        """
        # Cut captions into two pieces: captions_in has everything but the last
        # word and will be input to the RNN; captions_out has everything but the
        # first word and this is what we will expect the RNN to generate. These
        # are offset by one relative to each other because the RNN should produce
        # word (t+1) after receiving word t. The first element of captions_in
        # will be the START token, and the first element of captions_out will
        # be the first word.
        captions_in = captions[:, :-1]
        captions_out = captions[:, 1:]

        loss = 0.0
        ######################################################################
        # TODO: Implement the forward pass for the CaptioningRNN.
        # In the forward pass you will need to do the following:
        # (1) Use an affine transformation to project the image feature to
        #     the initial hidden state $h0$ (for RNN/LSTM, of shape (N, H)) or
        #     the projected CNN activation input $A$ (for Attention LSTM,
        #     of shape (N, H, 4, 4).
        # (2) Use a word embedding layer to transform the words in captions_in
        #     from indices to vectors, giving an array of shape (N, T, W).
        # (3) Use either a vanilla RNN or LSTM (depending on self.cell_type) to
        #     process the sequence of input word vectors and produce hidden state
        #     vectors for all timesteps, producing an array of shape (N, T, H).
        # (4) Use a (temporal) affine transformation to compute scores over the
        #     vocabulary at every timestep using the hidden states, giving an
        #     array of shape (N, T, V).
        # (5) Use (temporal) softmax to compute loss using captions_out, ignoring
        #     the points where the output word is <NULL>.
        #
        # Do not worry about regularizing the weights or their gradients!
        ######################################################################
        # Replace "pass" statement with your code
        # Extract features from the input images.
        features = self.imageEncoder(images)

        # apply average pooling to spatial dimensions for 'rnn' and 'lstm'
        if self.cell_type in ['rnn', 'lstm']:
            features = features.mean(dim=(2, 3))

        # Step (1): Use an affine transformation.
        # "featureProjector" behaviour depends on "cell_type":
        #  - For 'rnn' and 'lstm', we apply a linear layer. Output (h0) shape is (N, H)
        #  - For 'attention', we apply a conv layer. Output (A) shape is (N, H, 4, 4)
        # print('feat shape', features.shape)
        h0_A = self.featureProjector(features)

        # Step (2): Use a word embedding layer. "embed_words" shape is (N, T, W)
        embed_words = self.wordEmbedding(captions_in)

        # Step (3): Process the sequence of "embed_words" and produce hidden state vectors.
        # "hstates" is a tensor of shape (N, T, H)
        hstates = self.coreNetwork(embed_words, h0_A)

        # Step (4): Use a (temporal) affine transformation to compute scores over the vocabulary.
        # "scores" is a tensor of shape (N, T, V)
        scores = self.outProjector(hstates)

        # Step (5): Use (temporal) softmax to compute loss.
        loss = temporal_softmax_loss(scores, captions_out, self.ignore_index)
        ######################################################################
        #                           END OF YOUR CODE                         #
        ######################################################################

        return loss

    def sample(self, images, max_length=15):
        """
        Run a test-time forward pass for the model, sampling captions for input
        feature vectors.

        At each timestep, we embed the current word, pass it and the previous hidden
        state to the RNN to get the next hidden state, use the hidden state to get
        scores for all vocab words, and choose the word with the highest score as
        the next word. The initial hidden state is computed by applying an affine
        transform to the image features, and the initial word is the <START>
        token.

        For LSTMs you will also have to keep track of the cell state; in that case
        the initial cell state should be zero.

        Args:
            images: Input images, of shape (N, 3, 112, 112)
            max_length: Maximum length T of generated captions

        Returns:
            captions: Array of shape (N, max_length) giving sampled captions,
                where each element is an integer in the range [0, V). The first
                element of captions should be the first sampled word, not the
                <START> token.
        """
        N = images.shape[0]
        captions = self._null * images.new(N, max_length).fill_(1).long()

        if self.cell_type == "attn":
            attn_weights_all = images.new(N, max_length, 4, 4).fill_(0).float()

        ######################################################################
        # TODO: Implement test-time sampling for the model. You will need to
        # initialize the hidden state of the RNN by applying the learned affine
        # transform to the image features. The first word that you feed to
        # the RNN should be the <START> token; its value is stored in the
        # variable self._start. At each timestep you will need to do to:
        # (1) Embed the previous word using the learned word embeddings
        # (2) Make an RNN step using the previous hidden state and the embedded
        #     current word to get the next hidden state.
        # (3) Apply the learned affine transformation to the next hidden state to
        #     get scores for all words in the vocabulary
        # (4) Select the word with the highest score as the next word, writing it
        #     (the word index) to the appropriate slot in the captions variable
        #
        # For simplicity, you do not need to stop generating after an <END> token
        # is sampled, but you can if you want to.
        #
        # NOTE: we are still working over minibatches in this function. Also if
        # you are using an LSTM, initialize the first cell state to zeros.
        # For AttentionLSTM, first project the 1280x4x4 CNN feature activation
        # to $A$ of shape Hx4x4. The LSTM initial hidden state and cell state
        # would both be A.mean(dim=(2, 3)).
        #######################################################################
        # Replace "pass" statement with your code
        # Extract features from the input images.
        features = self.imageEncoder(images)

        # Get the device on which we are operating (CPU or GPU [CUDA]).
        DEVICE = features.device
        # Put "captions" to the actual device, as all other tensors are in this device.
        captions = captions.to(device=DEVICE)

        # Use an affine transformation.
        if self.cell_type in ['rnn', 'lstm']:
            # apply average pooling to spatial dimensions for 'rnn' and 'lstm':
            features = features.mean(dim=(2, 3))
            # Initialize the hidden state by applying the affine transform to the features.
            h = self.featureProjector(features)
            # For LSTM: initialize the first cell state to zeros.
            c = torch.zeros_like(h)
        else: # "cell_type" is 'attention'.
            # Put "attn_weights_all" to the actual device, as all other tensors are in this device.
            attn_weights_all = attn_weights_all.to(device=DEVICE)
            # Project the features to the the projected CNN activation input.
            A = self.featureProjector(features)
            # For AttentionLSTM: initial hidden state and cell state would both be A.mean(dim=(2, 3)).
            h, c = A.mean(dim=(2, 3)), A.mean(dim=(2, 3))

        # Initialize the words feeded to the RNN (for each minibatch sample) with the
        # <START> token.
        input = torch.tensor([self._start]).repeat(N)

        # Record whether each example in the minibatch has reached the end.
        notend = images.new_full((N,), True)
        
        # For each timestep, feed the input word to the RNN and get the next hidden state.
        for t in range(max_length):
            # Step 1: Embed the current word.
            embed_input = self.wordEmbedding(input)

            # Step 2: Make an RNN step.
            if self.cell_type == 'rnn':
                h = self.coreNetwork.step_forward(embed_input, h)
            elif self.cell_type == 'lstm':
                h, c = self.coreNetwork.step_forward(embed_input, h, c)
            else: # "cell_type" is 'attention'.
                attn, attn_weights = dot_product_attention(h, A)
                # Save current timestep attention weights (for visualization purpose).
                attn_weights_all[:, t] = attn_weights
                h, c = self.coreNetwork.step_forward(embed_input, h, c, attn)

            # Step 3: Apply the affine transformation to the next hidden state.
            scores = self.outProjector(h) # (N, V)
            
            # Step 4: Sample the next word and write it to the captions.
            input = scores.argmax(dim=1) # (N,)
            # If the next word is <END>, then mark the example as ended.
            notend[input == self._end] = False
            captions[notend, t] = input[notend]

            if not notend.any():
                break

        ######################################################################
        #                           END OF YOUR CODE                         #
        ######################################################################
        if self.cell_type == "attn":
            return captions, attn_weights_all.cpu()
        else:
            return captions


class LSTM(nn.Module):
    """Single-layer, uni-directional LSTM module."""

    def __init__(self, input_dim: int, hidden_dim: int):
        """
        Initialize a LSTM. Model parameters to initialize:
            Wx: Weights for input-to-hidden connections, of shape (D, 4H)
            Wh: Weights for hidden-to-hidden connections, of shape (H, 4H)
            b: Biases, of shape (4H,)

        Args:
            input_dim: Input size, denoted as D before
            hidden_dim: Hidden size, denoted as H before
        """
        super().__init__()

        # Register parameters
        self.Wx = nn.Parameter(
            torch.randn(input_dim, hidden_dim * 4).div(math.sqrt(input_dim))
        )
        self.Wh = nn.Parameter(
            torch.randn(hidden_dim, hidden_dim * 4).div(math.sqrt(hidden_dim))
        )
        self.b = nn.Parameter(torch.zeros(hidden_dim * 4))

    def step_forward(
        self, x: torch.Tensor, prev_h: torch.Tensor, prev_c: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Forward pass for a single timestep of an LSTM.
        The input data has dimension D, the hidden state has dimension H, and
        we use a minibatch size of N.

        Args:
            x: Input data for one time step, of shape (N, D)
            prev_h: The previous hidden state, of shape (N, H)
            prev_c: The previous cell state, of shape (N, H)
            Wx: Input-to-hidden weights, of shape (D, 4H)
            Wh: Hidden-to-hidden weights, of shape (H, 4H)
            b: Biases, of shape (4H,)

        Returns:
            Tuple[torch.Tensor, torch.Tensor]
                next_h: Next hidden state, of shape (N, H)
                next_c: Next cell state, of shape (N, H)
        """
        ######################################################################
        # TODO: Implement the forward pass for a single timestep of an LSTM.
        ######################################################################
        next_h, next_c = None, None
        # Replace "pass" statement with your code
        # Compute the input dot product (inprod), output shape is (N, 4H).
        inprod = x @ self.Wx
        # Compute the hidden dot product (hprod), output shape is (N, 4H).
        hprod = prev_h @ self.Wh
        # Compute the pre-activation (preact) sum, output shape is (N, 4H).
        preact = inprod + hprod + self.b

        # Split "preact" along the column-dim into 4 parts [each of shape (N, H)].
        # For that, we need to get the chunk size, which is simply "H".
        H = prev_h.shape[1]
        i, f, o, g = torch.split(preact, H, dim=1)

        # Compute respectively 'input', 'forget', 'output' and 'block' gates.
        i = torch.sigmoid(i)
        f = torch.sigmoid(f)
        o = torch.sigmoid(o)
        g = torch.tanh(g)

        # Compute the next cell state (next_c).
        next_c = f * prev_c + i * g
        # Compute the next hidden state (next_h).
        next_h = o * torch.tanh(next_c)
        ######################################################################
        #                           END OF YOUR CODE                         #
        ######################################################################
        return next_h, next_c

    def forward(self, x: torch.Tensor, h0: torch.Tensor) -> torch.Tensor:
        """
        Forward pass for an LSTM over an entire sequence of data. We assume an
        input sequence composed of T vectors, each of dimension D. The LSTM
        uses a hidden size of H, and we work over a minibatch containing N
        sequences. After running the LSTM forward, we return the hidden states
        for all timesteps.

        Note that the initial cell state is passed as input, but the initial
        cell state is set to zero. Also note that the cell state is not returned;
        it is an internal variable to the LSTM and is not accessed from outside.

        Args:
            x: Input data for the entire timeseries, of shape (N, T, D)
            h0: Initial hidden state, of shape (N, H)

        Returns:
            hn: The hidden state output.
        """

        c0 = torch.zeros_like(
            h0
        )  # we provide the intial cell state c0 here for you!
        ######################################################################
        # TODO: Implement the forward pass for an LSTM over entire timeseries
        ######################################################################
        hn = None
        # Replace "pass" statement with your code
        N, T, D = x.shape
        H = h0.shape[1]

        # Initialize the hidden states array for the entire timeseries.
        hn = h0.new_zeros((N, T, H))
        # Initialize the previous hidden state (prev_h) with the initial one.
        prev_h = h0
        # Initialize the cell state with c0.
        prev_c = c0

        # Loop over timeseries. Current time is "t" (integer).
        for t in range(T):
            # Get the minibatch for current "ts".
            x_t = x[:, t, :]
            # Apply the forward step, save results to prev for next time step.
            prev_h, prev_c = self.step_forward(x_t, prev_h, prev_c)
            # Save the hidden state for time "t".
            hn[:, t, :] = prev_h
        ######################################################################
        #                           END OF YOUR CODE                         #
        ######################################################################

        return hn


def dot_product_attention(prev_h, A):
    """
    A simple scaled dot-product attention layer.

    Args:
        prev_h: The LSTM hidden state from previous time step, of shape (N, H)
        A: **Projected** CNN feature activation, of shape (N, H, 4, 4),
         where H is the LSTM hidden state size

    Returns:
        attn: Attention embedding output, of shape (N, H)
        attn_weights: Attention weights, of shape (N, 4, 4)

    """
    N, H, D_a, _ = A.shape

    attn, attn_weights = None, None
    ##########################################################################
    # TODO: Implement the scaled dot-product attention we described earlier. #
    # You will use this function for `AttentionLSTM` forward and sample      #
    # functions. HINT: Make sure you reshape attn_weights back to (N, 4, 4)! #
    ##########################################################################
    # Replace "pass" statement with your code
    
    # Flatten the two last dims of "A". Now, "A" has a shape of (N, H, 16)
    A = torch.flatten(A, start_dim=2)

    # Add one dimension to "prev_h". Now, "prev_h" has a shape of (N, 1, H)
    prev_h = prev_h.unsqueeze(1)

    # Compute the attention weights.
    # shape: [(N, 1, H) @ (N, H, 16)] / <scalar>
    attn_weights = (prev_h @ A) / math.sqrt(H) # (N, 1, 16)
    attn_weights = torch.transpose(attn_weights, 1, 2)  # (N, 16, 1)
    # Apply the Softmax on "attn_weights"
    attn_weights = torch.softmax(attn_weights, dim=1)

    # Compute the attention embedding. attn.shape = (N, H, 16) @ (N, 16, 1) = (N, H, 1)
    attn = A @ attn_weights
    # Remove unit dims from "attn". "attn" will have a shape of (N, H)
    attn = attn.squeeze()

    # Reshape back "attn_weights" from (N, 16, 1) to (N, 4, 4)
    attn_weights = attn_weights.squeeze().reshape((N, 4, 4))
    
    ##########################################################################
    #                             END OF YOUR CODE                           #
    ##########################################################################

    return attn, attn_weights


class AttentionLSTM(nn.Module):
    """
    This is our single-layer, uni-directional Attention module.

    Args:
        input_dim: Input size, denoted as D before
        hidden_dim: Hidden size, denoted as H before
    """

    def __init__(self, input_dim: int, hidden_dim: int):
        """
        Initialize a LSTM. Model parameters to initialize:
            Wx: Weights for input-to-hidden connections, of shape (D, 4H)
            Wh: Weights for hidden-to-hidden connections, of shape (H, 4H)
            Wattn: Weights for attention-to-hidden connections, of shape (H, 4H)
            b: Biases, of shape (4H,)
        """
        super().__init__()

        # Register parameters
        self.Wx = nn.Parameter(
            torch.randn(input_dim, hidden_dim * 4).div(math.sqrt(input_dim))
        )
        self.Wh = nn.Parameter(
            torch.randn(hidden_dim, hidden_dim * 4).div(math.sqrt(hidden_dim))
        )
        self.Wattn = nn.Parameter(
            torch.randn(hidden_dim, hidden_dim * 4).div(math.sqrt(hidden_dim))
        )
        self.b = nn.Parameter(torch.zeros(hidden_dim * 4))

    def step_forward(
        self,
        x: torch.Tensor,
        prev_h: torch.Tensor,
        prev_c: torch.Tensor,
        attn: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Args:
            x: Input data for one time step, of shape (N, D)
            prev_h: The previous hidden state, of shape (N, H)
            prev_c: The previous cell state, of shape (N, H)
            attn: The attention embedding, of shape (N, H)

        Returns:
            next_h: The next hidden state, of shape (N, H)
            next_c: The next cell state, of shape (N, H)
        """

        #######################################################################
        # TODO: Implement forward pass for a single timestep of attention LSTM.
        # Feel free to re-use some of your code from `LSTM.step_forward()`.
        #######################################################################
        next_h, next_c = None, None
        # Replace "pass" statement with your code
        
        # Compute the input dot product (inprod), output shape is (N, 4H).
        inprod = x @ self.Wx
        # Compute the hidden dot product (hprod), output shape is (N, 4H).
        hprod = prev_h @ self.Wh
        # Compute the attention dot product (attnprod), output shape is (N, 4H).
        attnprod = attn @ self.Wattn
        # Compute the pre-activation (preact) sum, output shape is (N, 4H).
        preact = inprod + hprod + attnprod + self.b

        # Split "preact" along the column-dim into 4 parts [each of shape (N, H)].
        # For that, we need to get the chunk size, which is simply "H".
        H = prev_h.shape[1]
        i, f, o, g = torch.split(preact, H, dim=1)

        # Compute respectively 'input', 'forget', 'output' and 'block' gates.
        i = torch.sigmoid(i)
        f = torch.sigmoid(f)
        o = torch.sigmoid(o)
        g = torch.tanh(g)

        # Compute the next cell state (next_c).
        next_c = f * prev_c + i * g
        # Compute the next hidden state (next_h).
        next_h = o * torch.tanh(next_c)
        ######################################################################
        #                           END OF YOUR CODE                         #
        ######################################################################
        return next_h, next_c

    def forward(self, x: torch.Tensor, A: torch.Tensor):
        """
        Forward pass for an LSTM over an entire sequence of data. We assume an
        input sequence composed of T vectors, each of dimension D. The LSTM uses
        a hidden size of H, and we work over a minibatch containing N sequences.
        After running the LSTM forward, we return hidden states for all timesteps.

        Note that the initial cell state is passed as input, but the initial cell
        state is set to zero. Also note that the cell state is not returned; it
        is an internal variable to the LSTM and is not accessed from outside.

        h0 and c0 are same initialized as the global image feature (meanpooled A)
        For simplicity, we implement scaled dot-product attention, which means in
        Eq. 4 of the paper (https://arxiv.org/pdf/1502.03044.pdf),
        f_{att}(a_i, h_{t-1}) equals to the scaled dot product of a_i and h_{t-1}.

        Args:
            x: Input data for the entire timeseries, of shape (N, T, D)
            A: The projected CNN feature activation, of shape (N, H, 4, 4)

        Returns:
            hn: The hidden state output
        """

        # The initial hidden state h0 and cell state c0 are initialized
        # differently in AttentionLSTM from the original LSTM and hence
        # we provided them for you.
        h0 = A.mean(dim=(2, 3))  # Initial hidden state, of shape (N, H)
        c0 = h0  # Initial cell state, of shape (N, H)

        ######################################################################
        # TODO: Implement the forward pass for an LSTM over an entire time-  #
        # series. You should use the `dot_product_attention` function that   #
        # is defined outside this module.                                    #
        ######################################################################
        hn = None
        # Replace "pass" statement with your code
        N, T, _ = x.shape
        H = h0.shape[1]

        # Initialize the hidden states array for the entire timeseries.
        hn = h0.new_zeros((N, T, H))
        # Initialize the previous hidden state (prev_h) with the initial one.
        prev_h = h0
        # Initialize the cell state with c0.
        prev_c = c0

        # Loop over timeseries. Current time is "t" (integer).
        for t in range(T):
            # Get the minibatch for current "t".
            x_t = x[:, t, :]
            # Get the attention embedding for current "t".
            attn, _ = dot_product_attention(prev_h, A)
            # Apply the forward step, save results to prev for next time step.
            prev_h, prev_c = self.step_forward(x_t, prev_h, prev_c, attn)
            # Save the hidden state for time "t".
            hn[:, t, :] = prev_h
        ######################################################################
        #                           END OF YOUR CODE                         #
        ######################################################################
        return hn