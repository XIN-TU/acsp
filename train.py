import os
import time
import torch
import json
import torch.optim as optim
import numpy as np
import time
from copy import deepcopy
from torch.utils.data import DataLoader
from torchvision.transforms import ToTensor, Normalize, Compose, ColorJitter

from net.loss import *
from net.network_sn_101 import ACSPNet
from config import Config
from dataloader.loader import *
from sys import exit
ticks = time.time()

config = Config()
config.train_path = './data/citypersons'
config.test_path = './data/citypersons'
config.gpu_ids = [0, 1]
config.onegpu = 2
config.size_train = (640, 1280)
config.size_test = (1024, 2048)
config.init_lr = 2e-4
config.num_epochs = 150
config.val = False
config.offset = True
config.teacher = True

# dataset
print('Dataset...')
traintransform = Compose(
    [ColorJitter(brightness=0.5), ToTensor(), Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])])
traindataset = CityPersons(path=config.train_path, type='train', config=config,
                           transform=traintransform)
trainloader = DataLoader(traindataset, batch_size=config.onegpu*len(config.gpu_ids))


# net
print('Net...')
net = ACSPNet().cuda()

# To continue training
#net.load_state_dict(torch.load('./ckpt/ACSP_150.pth.tea'))


# position
center = cls_pos().cuda()
height = reg_pos().cuda()
offset = offset_pos().cuda()

# optimizer
params = []
for n, p in net.named_parameters():
    if p.requires_grad:
        params.append({'params': p})
    else:
        print(n)

if config.teacher:
    teacher_dict = net.state_dict()

net = nn.DataParallel(net, device_ids=config.gpu_ids)

optimizer = optim.Adam(params, lr=config.init_lr)


batchsize = config.onegpu * len(config.gpu_ids)
train_batches = len(trainloader)

config.print_conf()


def criterion(output, label):
    cls_loss = center(output[0], label[0])
    reg_loss = height(output[1], label[1])
    off_loss = offset(output[2], label[2])
    return cls_loss, reg_loss, off_loss


def train():

    print('Training start')
    if not os.path.exists('./ckpt'):
        os.mkdir('./ckpt')
    if not os.path.exists('./loss'):
        os.mkdir('./loss')
    if not os.path.exists('./log'):
        os.mkdir('./log')

    # open log file
    log_file = './log/' + time.strftime('%Y%m%d', time.localtime(time.time()))+'.log'
    log = open(log_file, 'w')

    best_loss = np.Inf
    best_loss_epoch = 0

    
    loss_list = []

    for epoch in range(0,150):
        print('----------')
        print('Epoch %d begin' % (epoch + 1))
        t1 = time.time()

        epoch_loss = 0.0
        net.train()

        for i, data in enumerate(trainloader, 0):

            t3 = time.time()
            # get the inputs
            inputs, labels = data
            inputs = inputs.cuda()
            labels = [l.cuda().float() for l in labels]

            # zero the parameter gradients
            optimizer.zero_grad()

            # heat map
            outputs = net(inputs)

            # loss
            cls_loss, reg_loss, off_loss = criterion(outputs, labels)
            loss = cls_loss + reg_loss + off_loss

            # back-prop
            loss.backward()

            # update param
            optimizer.step()
            if config.teacher:
                for k, v in net.module.state_dict().items():
                    if k.find('num_batches_tracked') == -1:#?????????
                        #print("Use mean teacher")
                        teacher_dict[k] = config.alpha * teacher_dict[k] + (1 - config.alpha) * v
                    else:
                        #print("Nullify mean teacher")
                        teacher_dict[k] = 1 * v

            # print statistics
            batch_loss = loss.item()
            batch_cls_loss = cls_loss.item()
            batch_reg_loss = reg_loss.item()
            batch_off_loss = off_loss.item()

            t4 = time.time()
            print('\r[Epoch %d/150, Batch %d/%d]$ <Total loss: %.6f> cls: %.6f, reg: %.6f, off: %.6f, Time: %.3f sec        ' %
                  (epoch + 1, i + 1, train_batches, batch_loss, batch_cls_loss, batch_reg_loss, batch_off_loss, t4-t3)),
            epoch_loss += batch_loss
        print('')

        t2 = time.time()
        epoch_loss /= len(trainloader)
        loss_list.append(epoch_loss)
        loss_out = np.array(loss_list)
        name = "./loss/loss_" + str(epoch) + ".npy"
        np.save(name,loss_out)
        
        print('Epoch %d end, AvgLoss is %.6f, Time used %.1f sec.' % (epoch+1, epoch_loss, int(t2-t1)))
        if epoch_loss < best_loss:
            best_loss = epoch_loss
            best_loss_epoch = epoch + 1
        print('Epoch %d has lowest loss: %.7f' % (best_loss_epoch, best_loss))

        
        log.write('%d %.7f\n' % (epoch+1, epoch_loss))
            
        print('Save checkpoint...')
        filename = './ckpt/%s_%d.pth' % ('ACSP',epoch+1)

        torch.save(net.module.state_dict(), filename)
        if config.teacher:
            torch.save(teacher_dict, filename+'.tea')

        print('%s saved.' % filename)

    log.close()



if __name__ == '__main__':
    train()
