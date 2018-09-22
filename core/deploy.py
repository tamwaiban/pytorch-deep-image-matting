import torch
import argparse
import torch.nn as nn
import net
import cv2
import os
from torchvision import transforms
import torch.nn.functional as F
import numpy as np
import time

def get_args():
    # Training settings
    parser = argparse.ArgumentParser(description='PyTorch Super Res Example')
    parser.add_argument('--size_h', type=int, required=True, help="height size of input image")
    parser.add_argument('--size_w', type=int, required=True, help="width size of input image")
    parser.add_argument('--imgDir', type=str, required=True, help="directory of image")
    parser.add_argument('--trimapDir', type=str, required=True, help="directory of trimap")
    parser.add_argument('--cuda', action='store_true', help='use cuda?')
    parser.add_argument('--resume', type=str, required=True, help="checkpoint that model resume from")
    parser.add_argument('--saveDir', type=str, required=True, help="where prediction result save to")
    parser.add_argument('--alphaDir', type=str, default='', help="directory of gt")
    parser.add_argument('--stage', type=int, required=True, help="backbone stage")
    parser.add_argument('--not_strict', action='store_true', help='not copy ckpt strict?')
    args = parser.parse_args()
    print(args)
    return args

def gen_dataset(imgdir, trimapdir):
        sample_set = []
        img_ids = os.listdir(imgdir)
        cnt = len(img_ids)
        cur = 1
        for img_id in img_ids:
            img_name = os.path.join(imgdir, img_id)
            trimap_name = os.path.join(trimapdir, img_id)

            assert(os.path.exists(img_name))
            assert(os.path.exists(trimap_name))

            sample_set.append((img_name, trimap_name))

        return sample_set


def main():

    print("===> Loading args")
    args = get_args()

    print("===> Environment init")
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"
    if args.cuda and not torch.cuda.is_available():
        raise Exception("No GPU found, please run without --cuda")
     
    model = net.DeepMatting(args)
    ckpt = torch.load(args.resume)
    if args.not_strict:
        model.load_state_dict(ckpt['state_dict'], strict=False)
    else:
        model.load_state_dict(ckpt['state_dict'], strict=True)

    if args.cuda:
        model = model.cuda()

    print("===> Load dataset")
    dataset = gen_dataset(args.imgDir, args.trimapDir)

    mse_diffs = 0.
    pixels = 0.
    cnt = len(dataset)
    cur = 1
    t0 = time.time()
    for img_path, trimap_path in dataset:
        img = cv2.imread(img_path)
        trimap = cv2.imread(trimap_path)[:, :, 0]
        img_info = (img_path.split('/')[-1], img.shape[0], img.shape[1])
        # resize
        img = cv2.resize(img, (args.size_w, args.size_h), interpolation=cv2.INTER_LINEAR)
        trimap = cv2.resize(trimap, (args.size_w, args.size_h), interpolation=cv2.INTER_LINEAR)
        # to Tensor
        img = torch.from_numpy(img.astype(np.float32)[np.newaxis, :, :, :]).permute(0, 3, 1, 2)
        trimap = torch.from_numpy(trimap.astype(np.float32)[np.newaxis, np.newaxis, :, :])
    
        print('[{}/{}] {}'.format(cur, cnt, img_info[0]))
        cur += 1
        if args.cuda:
            img = img.cuda()
            trimap = trimap.cuda()
        #print('Img Shape:{} Trimap Shape:{}'.format(img.shape, trimap.shape))
        assert(args.stage in [1, 2, 3])
        if args.stage == 1:
            # stage 1
            pred_mattes, _ = model(torch.cat((img, trimap), 1))
        else:
            # stage 2, 3
            _, pred_mattes = model(torch.cat((img, trimap), 1))
        # only attention unknown region
        pred_mattes[trimap == 255] = 1.
        pred_mattes[trimap == 0  ] = 0.

        pred_mattes = pred_mattes.data
        if args.cuda:
            pred_mattes = pred_mattes.cpu()
        pred_mattes = pred_mattes.numpy()[0, 0, :, :]

        # resize to origin size
        origin_pred_mattes = cv2.resize(pred_mattes, (img_info[2], img_info[1]), interpolation = cv2.INTER_LINEAR)
        origin_pred_mattes = (origin_pred_mattes * 255).astype(np.uint8)
        cv2.imwrite(os.path.join(args.saveDir, img_info[0]), origin_pred_mattes)

        pixels = pixels + ((trimap == 128).sum())
        # eval if gt alpha is given
        if args.alphaDir != '':
            alpha_name = os.path.join(args.alphaDir, img_info[0])
            assert(os.path.exists(alpha_name))
            alpha = cv2.imread(alpha_name)[:, :, 0]
            assert(alpha.shape == origin_pred_mattes.shape)
            assert(type(alpha) == type(origin_pred_mattes))
            diff = ((origin_pred_mattes - alpha) ** 2).sum()
            mse_diffs += diff
    print("Avg-Cost: {} s/image".format((time.time() - t0) / cnt))
    print("Eval-MSE: {}".format(mse_diffs / pixels))

if __name__ == "__main__":
    main()
