import torch
from torch import nn
from torch.nn import functional as F
from torch.distributions.normal import Normal
from lib.utils.vis_logger import logger


class VAE(nn.Module):
    def __init__(self, dim_in, dim_latent):
        nn.Module.__init__(self)
        self.dim_latent = dim_latent
        self.encoder = MLP(dim_in, 256, 256, 'relu')
        self.gaussian = GaussianLayer(256, dim_latent)
        self.decoder = MLP(dim_latent, 256, dim_in, 'sigmoid')
        self.bce = nn.BCELoss(reduction='none')
        
    def forward(self, x, n_samples=1, reduce=True):
        """
        This forward pass is used for training. Only one sample will be used.
        :param x: (B, 1, H, W)
        """
        # (B, N)
        elbo = self.elbo(x, n_samples=n_samples)
        
        # note the negative sign
        if reduce:
            elbo = elbo.mean()
        return -elbo
        # return bce
    
    def elbo(self, x, n_samples=1):
        """
        Evaluates elbo for each sample (not averaged)
        :param x: (B, 1, H, W)
        :return:
            elbo: (B, N)
        """
        B = x.size(0)
        x = x.view(B, -1)
        org = x.clone()
        # (B, D)
        x = self.encoder(x)
        # (B, N, L)
        x = self.gaussian(x, n_samples)
        # (B, N, D)
        x = self.decoder(x)
        # broadcast input
        x, org = torch.broadcast_tensors(x, org[:, None, :])
        # (B, N, D)
        bce = self.bce(x, org)
        # (B, N)
        bce = bce.sum(dim=-1)
        # (B,)
        kl = self.gaussian.kl_divergence()

        logger.update(image=org[0, 0].view(28, 28))
        logger.update(pred=x[0, 0].view(28, 28))
        logger.update(bce=bce.mean())
        logger.update(kl=kl.mean())
        # generate from unit gaussian
        z = torch.randn(1, self.dim_latent).to(x.device)
        gen = self.decoder(z)
        logger.update(gen=gen.view(1, 28, 28)[0])

        return -bce - kl[:, None]
    
class MLP(nn.Module):
    def __init__(self, dim_in, dim_h, dim_out, act):
        nn.Module.__init__(self)
        self.dim_in = dim_in
        self.dim_out = dim_out
        self.fc1 = nn.Linear(dim_in, dim_h)
        self.fc2 = nn.Linear(dim_h, dim_out)
        self.act = act
        
    def forward(self, x):
        """
        Dimension preserving
        :param x: (B, *, D_in)
        :return: (B, *, D_out)
        """
        # A will contain any other size
        *A, _ = x.size()
        # reshape
        x = x.view(-1, self.dim_in)
        x = F.relu(self.fc1(x))
        if self.act == 'relu':
            x = F.relu(self.fc2(x))
        else:
            x = torch.sigmoid(self.fc2(x))
            
        x = x.view(*A, self.dim_out)
        
        return x
    
class GaussianLayer(nn.Module):
    def __init__(self, dim_in, dim_latent):
        nn.Module.__init__(self)
        self.mean_layer = nn.Linear(dim_in, dim_latent)
        # log variance here
        self.log_var_layer = nn.Linear(dim_in, dim_latent)
        
        # self.normal = Normal(0, 1)
        
    def forward(self, x, n_samples):
        """
        :param x: input from encoder (B, D)
        :return: (B, N, D), where N is the number of samples
        """
        # (B, L)
        self.mean = self.mean_layer(x)
        # log standard deviation here
        self.log_var = self.log_var_layer(x)
        log_dev = 0.5 * self.log_var
        # standard deviation
        dev = torch.exp(log_dev)
        
        # sample
        # (B, 1, D), (B, 1, D)
        N = n_samples
        B, D = self.mean.size()
        mean = self.mean[:, None, :]
        dev = dev[:, None, :]
        epsilon = torch.randn(B, N, D).to(self.mean.device)
        
        return mean + dev * epsilon
    
    def kl_divergence(self):
        """
        Compute KL divergence between estimated dist and standrad gaussian
        return: mean KL
        """
        var = torch.exp(self.log_var)
        # (B, L)
        kl = 0.5 * (var + self.mean ** 2 - 1 - self.log_var)
        # sum over data dimension
        kl = kl.sum(dim=1)
        return kl
        
        
