"""Evaluate and invert a saved historical-plane thin-plate spline."""
import numpy as np

class AtlasTPS:
    def __init__(self, record, affine_report):
        self.centre=np.array(record['pixel_centre']);self.scale=record['pixel_scale'];self.plane_scale=record['plane_scale']
        self.knots=np.array(record['knots']);self.weights=np.array(record['kernel_weights']);self.tail=np.array(record['affine_tail'])
        self.affine_centre=np.array(affine_report['affine_plane_centre_fathoms']);self.affine=np.array(affine_report['affine_coefficients'])

    def forward(self, pixels, jacobian=False):
        uv=(np.asarray(pixels)-self.centre)/self.scale
        dx=uv[:,None,0]-self.knots[None,:,0];dy=uv[:,None,1]-self.knots[None,:,1]
        r2=dx*dx+dy*dy;log=np.log(np.maximum(r2,1e-300))
        plane=(np.column_stack([np.ones(len(uv)),uv])@self.tail+(.5*r2*log)@self.weights)*self.plane_scale
        if not jacobian:return plane
        gx=(self.tail[1]+((log+1)*dx)@self.weights)*self.plane_scale/self.scale
        gy=(self.tail[2]+((log+1)*dy)@self.weights)*self.plane_scale/self.scale
        return plane,np.stack([gx,gy],axis=2)

    def inverse(self, plane):
        plane=np.asarray(plane)
        pixels=np.column_stack([np.ones(len(plane)),(plane-self.affine_centre)/100000])@self.affine
        for iteration in range(12):
            found,jac=self.forward(pixels,True);error=found-plane
            if np.max(abs(error))<1e-4:return pixels
            det=jac[:,0,0]*jac[:,1,1]-jac[:,0,1]*jac[:,1,0]
            if np.any(abs(det)<1e-5):raise ValueError('TPS inverse encountered singular Jacobian')
            step=np.column_stack([(jac[:,1,1]*error[:,0]-jac[:,0,1]*error[:,1])/det,
                                  (-jac[:,1,0]*error[:,0]+jac[:,0,0]*error[:,1])/det])
            pixels-=np.clip(step,-500,500)
        raise ValueError('TPS inverse did not converge')
