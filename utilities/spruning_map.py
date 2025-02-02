import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import torch
import torch_pruning as tp
from yolo.yolo2 import Yolo_Block
from train.train import train_model, RAdam , test_model
from yolo.CSP import ConvBlock
from yolo.backbone import backbone
import numpy as np
from utilities.utils import  mean_average_precision,get_evaluation_bboxes, use_gpu_if_possible

from loss import Loss

import torch.nn as nn
from utils import class_accuracy
from dataset.dataset import get_data

import tensorflow as tf


def prune_model(model, amount = 0.5):
    
    model.cpu()
    
    # forward the model with a fake input to 
    # compute a dependency graph
    DG = tp.DependencyGraph().build_dependency( model, torch.randn(1, 3, 416, 416) )
    
    def prune_conv(conv, amount=amount):
        
        strategy = tp.strategy.L1Strategy() # setup strategy 
        pruning_index = strategy(conv.weight, amount=amount)
        plan = DG.get_pruning_plan(conv, tp.prune_conv, pruning_index)
        plan.exec() 
    
    
    for m in model.modules():
        if isinstance( m, ConvBlock ):
            prune_conv( m.conv)
        
        
            
    return model   


if __name__ == '__main__':
    
    train_loader, test_loader = get_data('./dataset/train.csv','./dataset/test.csv')
    S=[13, 26]
    ANCHORS =  [[(0.275 ,   0.320312), (0.068   , 0.113281), (0.017  ,  0.03   )], 
               [(0.03  ,   0.056   ), (0.01  ,   0.018   ), (0.006 ,   0.01    )]]

    scaled_anchors = (
            torch.tensor(ANCHORS)
            * torch.tensor(S).unsqueeze(1).unsqueeze(1).repeat(1, 3, 2)
        ).to("cuda:0")

    def test(p):



        model = Yolo_Block(3,3,2)
        model.load_state_dict(torch.load('./models/model.pt'))
    
        params = sum([np.prod(p.size()) for p in model.parameters()])
        print("Number of Parameters: %.1fM"%(params/1e6))
        test_model(model, test_loader, scaled_anchors, performance=class_accuracy, loss_fn= Loss(), device=None)


        prune_model(model, p)
        params = sum([np.prod(p.size()) for p in model.parameters()])
        print("Number of Parameters: %.1fM"%(params/1e6))
        num_epochs = 20
        optimizer = RAdam(model.parameters(), lr=0.001/5, weight_decay=0.005)
        scaler = torch.cuda.amp.GradScaler()       
        # Retrain the model
        train_model(train_loader, model, optimizer, Loss(), num_epochs, scaler,  scaled_anchors,None, performance=class_accuracy,lr_scheduler= None,epoch_start_scheduler= 40)
        
        model.eval()
        test_model(model, test_loader, scaled_anchors, performance=class_accuracy, loss_fn= Loss(), device=None)



        pred_boxes, true_boxes = get_evaluation_bboxes(
            test_loader,
            model,
            iou_threshold = 0.5,
            anchors=ANCHORS,
            threshold=0.05,
	    device="cuda:0"
        )

        mapval = mean_average_precision(
            pred_boxes,
            true_boxes,
            iou_threshold=0.5,
            num_classes=2,
        )
        print(f"MAP: {mapval.item()}")

    pruning_rates = [0.8,0.9]

    for p in pruning_rates:
        test(p)

