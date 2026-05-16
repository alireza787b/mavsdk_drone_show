import { uploadLeaderTrajectoryCsv } from './swarmTrajectoryAssignment';

describe('swarmTrajectoryAssignment', () => {
  it('uploads the shared leader CSV filename through the provided service', async () => {
    const uploadFn = jest.fn().mockResolvedValue({ success: true, message: 'uploaded' });

    const result = await uploadLeaderTrajectoryCsv({
      leaderId: 3,
      csvContent: 'Name,Latitude\nWP1,35',
      uploadFn,
    });

    expect(result.success).toBe(true);
    expect(uploadFn).toHaveBeenCalledWith(3, expect.any(Blob), 'Drone 3.csv');
  });

  it('rejects missing leaders and failed uploads with actionable errors', async () => {
    await expect(uploadLeaderTrajectoryCsv({
      leaderId: '',
      csvContent: 'csv',
      uploadFn: jest.fn(),
    })).rejects.toThrow(/leader/i);

    await expect(uploadLeaderTrajectoryCsv({
      leaderId: 1,
      csvContent: 'csv',
      uploadFn: jest.fn().mockResolvedValue({ success: false, error: 'not top leader' }),
    })).rejects.toThrow('not top leader');
  });
});
