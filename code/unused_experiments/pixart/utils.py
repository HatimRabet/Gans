import numpy as np
from torch.utils.data import Dataset
import os
from PIL import Image
import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import transforms




class ConstructDataset(Dataset):
    def __init__(self, image_dir, transform=None):
        """
        Args:
            image_dir (str): Directory with all the images.
            transform (callable, optional): Optional transform to be applied on an image.
        """
        self.image_dir = image_dir
        self.transform = transform

        # List all files in the directory
        self.image_files = [f for f in os.listdir(image_dir) if os.path.isfile(os.path.join(image_dir, f))][:1000]

    def __len__(self):
        """
        Returns the number of samples in the dataset.
        """
        return len(self.image_files)
    
    def __getitem__(self, idx):
        """
        Retrieves an image sample at the given index.

        Args:
            idx (int): Index of the sample to retrieve.

        Returns:
            image (Tensor): The transformed image.
        """
        img_name = os.path.join(self.image_dir, self.image_files[idx])
        image = Image.open(img_name).convert('RGB')  # Open image and convert to RGB

        if self.transform:
            image = self.transform(image)

        return image


class Generator(nn.Module):
    def __init__(self, latent_dim, channels_out):
        super(Generator, self).__init__()
        self.model = nn.Sequential(
            # Input: latent_dim x 1 x 1
            # Upscale to 4x4
            nn.ConvTranspose2d(latent_dim, 1024, 4, 1, 0, bias=False),
            nn.BatchNorm2d(1024),
            nn.ReLU(),

            # Upscale to 8x8
            nn.ConvTranspose2d(1024, 512, 4, 2, 1, bias=False),
            nn.Tanh()  

        )

        # Final layer to upscale to 128x128
        self.final_layer = nn.ConvTranspose2d(512, channels_out, 4, 2, 1, bias=False)

    def forward(self, x):
        x = self.model(x)
        x = self.final_layer(x)
        return x

    

class Discriminator(nn.Module):
    def __init__(self, channels_in):
        super(Discriminator, self).__init__()
        self.model = nn.Sequential(
            # Input: (channels_in, 16, 16)
            nn.Conv2d(channels_in, 64, 4, 2, 1, bias=False),  # Output: (64, 8, 8)
            nn.LeakyReLU(0.2, inplace=True),
            
            nn.Conv2d(64, 128, 4, 2, 1, bias=False),  # Output: (128, 4, 4)
            nn.BatchNorm2d(128),
            nn.Dropout(p=0.2),
            nn.LeakyReLU(0.2, inplace=True),
            
            nn.Conv2d(128, 256, 4, 2, 1, bias=False),  # Output: (256, 2, 2)
            nn.BatchNorm2d(256),
            nn.Dropout(p=0.2),
            nn.LeakyReLU(0.2, inplace=True),
            
            nn.Conv2d(256, 512, 4, 2, 1, bias=False),  # Output: (512, 1, 1)
            # nn.BatchNorm2d(512),
            nn.Dropout(p=0.2),
            nn.LeakyReLU(0.2, inplace=True),
            
            # nn.Conv2d(256, 1, kernel_size=1, stride=1, padding=0, bias=False) # Output: (1, 1, 1)
        )
        self.fc = nn.Sequential(
            nn.Linear(512, 1),  # Convert the final output to a single scalar
            nn.Sigmoid()  # Output probability
        )

    def forward(self, x):
        x = self.model(x)
        x = torch.flatten(x, 1)  # Flatten the output to (batch_size, 1)
        return self.fc(x)


class DoubleConv(nn.Module):
    def __init__(self, input_channels, output_channels):
        super().__init__()
        self.doubleConv = nn.Sequential(
            nn.Conv2d(input_channels, output_channels, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv2d(output_channels, output_channels, kernel_size=3, padding=1),
            nn.ReLU()
        )
    
    def forward(self, x):
        return self.doubleConv(x)
    

class DownSample(nn.Module):
    def __init__(self, input_channels, output_channels):
        super().__init__()
        self.conv = DoubleConv(input_channels, output_channels)
        self.max_pool = nn.MaxPool2d(kernel_size=2, stride=2)

    def forward(self, x):
        x1 = self.conv(x)
        return x1, self.max_pool(x1)

class UpSample(nn.Module):
    def __init__(self, input_channels, output_channels):
        super().__init__()
        self.Upsample = nn.ConvTranspose2d(input_channels, input_channels // 2, kernel_size=2, stride=2)
        self.conv = DoubleConv(input_channels, output_channels)

    def forward(self, x1, x2):
        x1 = self.Upsample(x1)
        x = torch.cat([x1,x2], 1)
        return self.conv(x)


class Unet_Discriminator(nn.Module):
    def __init__(self, input_channels, n_classes):
        super().__init__()

        self.down_1 = DownSample(input_channels, 64)
        self.down_2 = DownSample(64, 128)
        self.down_3 = DownSample(128, 256)
        self.down_4 = DownSample(256, 512)
        self.down_5 = DownSample(512, 1024)

        self.fc1 = nn.Linear(1024 * 1, 1, bias=False)
        self.activation_1 = nn.Sigmoid()

        self.bottle_neck = DoubleConv(1024, 2048)

        self.up_1 = UpSample(2048, 1024)
        self.up_2 = UpSample(1024, 512)
        self.up_3 = UpSample(512, 256)
        self.up_4 = UpSample(256, 128)
        self.up_5 = UpSample(128, 64)

        self.output = nn.Conv2d(in_channels=64, out_channels=1, kernel_size=1) 

    def forward(self, x):
        down1, p1 = self.down_1(x)
        down2, p2 = self.down_2(p1)
        down3, p3 = self.down_3(p2)
        down4, p4 = self.down_4(p3)
        down5, p5 = self.down_5(p4)

        p5_pooled = torch.sum(p5, dim=[2,3])
        out_1 = self.fc1(p5_pooled)
        out_1 = self.activation_1(out_1)
        b = self.bottle_neck(p5)


        up1 = self.up_1(b, down5)
        up2 = self.up_2(up1, down4)
        up3 = self.up_3(up2, down3)
        up4 = self.up_4(up3, down2)
        up5 = self.up_5(up4, down1)

        out_2 = self.output(up5)
        out_2 = self.activation_1(out_2)

        return out_1, out_2
    
class Unet_Discriminator_V2(nn.Module):
    def __init__(self, input_channels, n_classes):
        super().__init__()

        self.down_1 = DownSample(input_channels, 64)
        self.down_2 = DownSample(64, 128)
        self.down_3 = DownSample(128, 256)

        self.fc1 = nn.Linear(256 * 1, 1, bias=False)
        self.activation_1 = nn.Sigmoid()

        self.bottle_neck = DoubleConv(256, 512)

        self.up_1 = UpSample(512, 256)
        self.up_2 = UpSample(256, 128)
        self.up_3 = UpSample(128, 64)

        self.output = nn.Conv2d(in_channels=64, out_channels=1, kernel_size=1) 

    def forward(self, x):
        down1, p1 = self.down_1(x)
        down2, p2 = self.down_2(p1)
        down3, p3 = self.down_3(p2)

        p3_pooled = torch.sum(p3, dim=[2,3])
        out_1 = self.fc1(p3_pooled)
        out_1 = self.activation_1(out_1)
        b = self.bottle_neck(p3)


        up1 = self.up_1(b, down3)
        up2 = self.up_2(up1, down2)
        up3 = self.up_3(up2, down1)

        out_2 = self.output(up3)
        out_2 = self.activation_1(out_2)

        return out_1, out_2
    
class Unet_Generator_V2(nn.Module):
    def __init__(self, latent_dim, channels_out):
        super(Unet_Generator_V2, self).__init__()
        self.model = nn.Sequential(
            # Input: latent_dim x 1 x 1
            nn.ConvTranspose2d(latent_dim, 64, 4, 1, 0, bias=False),
            nn.BatchNorm2d(64),
            nn.ReLU(),

            # Upscale to 4x4
            nn.ConvTranspose2d(64, 32, 4, 2, 1, bias=False),
            nn.BatchNorm2d(32),
            nn.ReLU(),

            # Upscale to 16x16
            nn.ConvTranspose2d(32, channels_out, 4, 2, 1, bias=False),
            nn.Tanh()  # Output: channels_out x 16 x 16
        )

        # Final layer to upscale to 256x256
        # self.final_layer = nn.ConvTranspose2d(channels_out, channels_out, 4, 2, 1, bias=False)

    def forward(self, x):
        x = self.model(x)
        # x = self.final_layer(x)
        return x
    

class Unet_Generator(nn.Module):
    def __init__(self, latent_dim, channels_out):
        super(Unet_Generator, self).__init__()
        self.model = nn.Sequential(
            # Input: latent_dim x 1 x 1
            nn.ConvTranspose2d(latent_dim, 1024, 4, 1, 0, bias=False),
            nn.BatchNorm2d(1024),
            nn.ReLU(),

            # Upscale to 4x4
            nn.ConvTranspose2d(1024, 512, 4, 2, 1, bias=False),
            nn.BatchNorm2d(512),
            nn.ReLU(),

            # Upscale to 8x8
            nn.ConvTranspose2d(512, 256, 4, 2, 1, bias=False),
            nn.BatchNorm2d(256),
            nn.ReLU(),

            # Upscale to 16x16
            nn.ConvTranspose2d(256, 128, 4, 2, 1, bias=False),
            nn.BatchNorm2d(128),
            nn.ReLU(),

            # Upscale to 32x32
            nn.ConvTranspose2d(128, 64, 4, 2, 1, bias=False),
            nn.BatchNorm2d(64),
            nn.ReLU(),

            # Upscale to 64x64
            nn.ConvTranspose2d(64, channels_out, 4, 2, 1, bias=False),
            nn.Tanh()  # Output: channels_out x 128 x 128
        )

        # Final layer to upscale to 256x256
        # self.final_layer = nn.ConvTranspose2d(channels_out, channels_out, 4, 2, 1, bias=False)

    def forward(self, x):
        x = self.model(x)
        # x = self.final_layer(x)
        return x
    
def unet_d_criterion_without_cutmix(output, label, batch_size):
    out_1, out_2 = output
    label_2 = label.view(batch_size, 1, 1, 1)
    label_2 = label_2.expand(-1, 1, 128, 128)

    out_1 = torch.clamp(out_1, 1e-10, 1 - 1e-10)
    out_2 = torch.clamp(out_2, 1e-10, 1 - 1e-10)

    loss_1 = F.binary_cross_entropy(out_1, label, reduction='sum')
    loss_2 = F.binary_cross_entropy(out_2, label_2, reduction='sum')

    return (loss_1 + loss_2) / batch_size


def unet_d_criterion_without_cutmix_v2(output, label, batch_size):
    out_1, out_2 = output
    label_2 = label.view(batch_size, 1, 1, 1)
    label_2 = label_2.expand(-1, 1, 16, 16)

    out_1 = torch.clamp(out_1, 1e-10, 1 - 1e-10)
    out_2 = torch.clamp(out_2, 1e-10, 1 - 1e-10)

    loss_1 = F.binary_cross_entropy(out_1, label, reduction='sum')
    loss_2 = F.binary_cross_entropy(out_2, label_2, reduction='sum')

    return (loss_1 + loss_2) / batch_size



def unet_d_criterion_with_cutmix(output, M, batch_size, epsilon=1e-10):
    out_1, out_2 = output

    # Ensure values are within a range to prevent log(0)
    out_1 = torch.clamp(out_1, min=epsilon, max=1-epsilon)
    out_2 = torch.clamp(out_2, min=epsilon, max=1-epsilon)
    
    # Compute log values
    loss_1 = -torch.sum(torch.log(out_1)) 

    p1 = out_2 * M
    p2 = out_2 * (1 - M)
    
    p1 = torch.clamp(p1, min=epsilon, max=1-epsilon)
    p2 = torch.clamp(p2, min=epsilon, max=1-epsilon)
    
    # Loss computation for p1 and p2
    loss_2 = -torch.sum(M * torch.log(p1) + (1 - M) * torch.log(p2))

    return (loss_1 + loss_2) / batch_size


# def rand_bbox(size, lam):
#     W = size[-2]
#     H = size[-1]
#     cut_rat = np.sqrt(1. - lam)
#     cut_w = int(W * cut_rat)
#     cut_h = int(H * cut_rat)

#     # uniform
#     cx = np.random.randint(W)
#     cy = np.random.randint(H)

#     bbx1 = np.clip(cx - cut_w // 2, 0, W)
#     bby1 = np.clip(cy - cut_h // 2, 0, H)
#     bbx2 = np.clip(cx + cut_w // 2, 0, W)
#     bby2 = np.clip(cy + cut_h // 2, 0, H)

#     return bbx1, bby1, bbx2, bby2


W, H = 128, 128



def generate_CutMix_samples(real_batch, fake_batch, D_unet):
    # generate mixed sample
    ratio = np.random.rand()
    size = real_batch.size()
    W, H = size[2], size[3]

    batch_size = size[0]
    rand_indices = torch.randperm(batch_size)

    target_a = real_batch.clone()  # Clone real images
    target_b = fake_batch[rand_indices].clone()  # Clone shuffled fake images

    # Generate random bounding box
    bbx1, bby1, bbx2, bby2 = rand_bbox(size, ratio)

    # Generate the mask for CutMix
    mask = torch.ones_like(real_batch)
    mask[:, :, bbx1:bbx2, bby1:bby2] = 0  # Masking the mixed region

    # Use torch.where to apply the CutMix without in-place modification
    cutmixed = torch.where(mask == 1, target_a, target_b)

    # adjust lambda to exactly match pixel ratio
    ratio = 1 - ((bbx2 - bbx1) * (bby2 - bby1) / (W * H))

    # Generate cutmix that will be used in the loss
    D_decoder, D_g_decoder = D_unet(target_a)[1], D_unet(target_b)[1]

    # Use torch.where to apply the CutMix in decoded results
    cutmixed_decoded = torch.where(mask == 1, D_decoder, D_g_decoder)

    return ratio, cutmixed, cutmixed_decoded, target_a, target_b, bbx1, bbx2, bby1, bby2



def generate_CutMix_samples(real_batch, fake_batch, D_unet, device=torch.device('cpu')):
    batch_size, _, H, W = real_batch.size()

    # Generate random ratios for the batch
    ratios = torch.rand(batch_size, device=device)

    # Randomly permute the fake batch for CutMix
    rand_indices = torch.randperm(batch_size, device=device)

    target_a = real_batch.clone()
    target_b = fake_batch[rand_indices].clone()

    # Generate bounding boxes for each image in the batch
    bbx1, bby1, bbx2, bby2 = rand_bbox(real_batch.size(), ratios, device)

    # Apply CutMix using batch indexing
    cutmixed = real_batch.clone()
    for i in range(batch_size):
        cutmixed[i, :, bbx1[i]:bbx2[i], bby1[i]:bby2[i]] = target_b[i, :, bbx1[i]:bbx2[i], bby1[i]:bby2[i]]

    # Adjust ratios to match pixel ratio for each image
    ratios = 1 - ((bbx2 - bbx1) * (bby2 - bby1) / (W * H))

    # Generate CutMix for the decoded outputs
    D_decoder, D_g_decoder = D_unet(target_a)[1], D_unet(target_b)[1]
    cutmixed_decoded = D_decoder.clone()
    for i in range(batch_size):
        cutmixed_decoded[i, :, bbx1[i]:bbx2[i], bby1[i]:bby2[i]] = D_g_decoder[i, :, bbx1[i]:bbx2[i], bby1[i]:bby2[i]]

    return ratios, cutmixed, cutmixed_decoded, target_a, target_b, bbx1, bbx2, bby1, bby2


def rand_bbox(size, ratios,device):
    batch_size, _, H, W = size
    # Compute bounding box for each image based on its ratio
    cut_ratios = torch.sqrt(1 - ratios).to(device)  # sqrt for CutMix formula

    bbx1 = torch.randint(0, W, (batch_size,), device=device)
    bby1 = torch.randint(0, H, (batch_size,), device=device)

    bbx2 = torch.clamp(bbx1 + (cut_ratios * W).long(), max=W)
    bby2 = torch.clamp(bby1 + (cut_ratios * H).long(), max=H)

    return bbx1, bby1, bbx2, bby2




def mix(M, G, x):
    mixed = M * x + (1 - M) * G
    return mixed 


def loss_encoder(output, labels):
    loss = F.binary_cross_entropy(output, labels, reduction='sum')
    return loss

def loss_decoder(output, labels):
    loss = F.binary_cross_entropy(output, labels, reduction='sum')
    return loss

def loss_regularization(output, target):
    loss = F.pairwise_distance(output, target, p=2, keepdim=False).sum()
    return loss